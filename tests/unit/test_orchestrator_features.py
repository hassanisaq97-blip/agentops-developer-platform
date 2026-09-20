"""Enhedstests for orchestratorens nye funktioner: skills, memory, dynamisk tool
discovery og checkpoint/pause — alle testet uden en spawnet MCP-subprocess (en
fake MCPClient monkeypatches `agentops.agent.orchestrator.MCPClient`), så
testene forbliver hurtige. Den fulde kæde (rigtig MCP-server) er stadig
dækket af tests/integration/test_orchestrator_end_to_end.py.
"""

from __future__ import annotations

from agentops.agent.orchestrator import AgentOrchestrator
from agentops.agent.schemas import AgentRunResult, TaskStatus
from agentops.gateway.base import LLMProvider
from agentops.gateway.gateway import LLMGateway
from agentops.gateway.router import ModelRouter
from agentops.gateway.schemas import (
    ChatRole,
    CompletionRequest,
    CompletionResult,
    Message,
    StopReason,
    TokenUsage,
    ToolCall,
    ToolDefinition,
)
from agentops.memory.schemas import MemoryCategory, MemoryRecord
from agentops.settings import Settings

_ALL_TOOL_NAMES = [
    "search_code",
    "read_file",
    "list_repository",
    "get_git_diff",
    "get_project_documentation",
    "get_repository_status",
    "run_tests",
    "edit_file",
    "apply_patch",
]


class _FakeMCPClient:
    """Erstatter en rigtig, spawnet MCP-server-subprocess for hurtige enhedstests."""

    def __init__(self, tool_result: str = '{"ok": true}'):
        self.calls: list[tuple[str, dict]] = []
        self._tool_result = tool_result

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def list_tool_definitions(self) -> list[ToolDefinition]:
        return [ToolDefinition(name=n, description=n) for n in _ALL_TOOL_NAMES]

    async def call_tool(self, name: str, arguments: dict) -> str:
        self.calls.append((name, arguments))
        return self._tool_result


class _RecordingProvider(LLMProvider):
    """Registrerer hver `CompletionRequest`, den modtager, og returnerer scriptede svar."""

    name = "test"

    def __init__(self, results: list[CompletionResult]):
        self._results = list(results)
        self.requests: list[CompletionRequest] = []

    def complete(self, request: CompletionRequest, *, model: str) -> CompletionResult:
        self.requests.append(request)
        return self._results.pop(0)


def _final_answer_result(text: str = "Færdig.") -> CompletionResult:
    return CompletionResult(
        message=Message(role=ChatRole.ASSISTANT, content=text, tool_calls=[]),
        stop_reason=StopReason.END_TURN,
        usage=TokenUsage(input_tokens=5, output_tokens=5),
        latency_ms=1.0,
        provider="test",
        model="deterministic-v1",
    )


def _tool_use_result(name: str, arguments: dict | None = None) -> CompletionResult:
    return CompletionResult(
        message=Message(
            role=ChatRole.ASSISTANT,
            content=None,
            tool_calls=[ToolCall(id="call_1", name=name, arguments=arguments or {})],
        ),
        stop_reason=StopReason.TOOL_USE,
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        latency_ms=1.0,
        provider="test",
        model="deterministic-v1",
    )


def _build(
    results: list[CompletionResult],
    *,
    settings: Settings | None = None,
    memory_retriever=None,
    memory_saver=None,
) -> tuple[AgentOrchestrator, _RecordingProvider]:
    settings = settings or Settings(llm_default_provider="test")
    provider = _RecordingProvider(results)
    gateway = LLMGateway({"test": provider}, ModelRouter(settings), fallback_provider=None)
    orchestrator = AgentOrchestrator(
        gateway, settings, memory_retriever=memory_retriever, memory_saver=memory_saver
    )
    return orchestrator, provider


async def test_skill_selection_augments_system_prompt(monkeypatch, tmp_path):
    fake_client = _FakeMCPClient()
    monkeypatch.setattr("agentops.agent.orchestrator.MCPClient", lambda *a, **k: fake_client)
    orchestrator, provider = _build([_final_answer_result()])

    result = await orchestrator.run("Der er en bug — testen fejler med en exception.", tmp_path)

    assert result.skill_selected == "debugging"
    assert "Aktiveret skill: debugging" in provider.requests[0].system
    assert any(e.type.value == "skill_selected" for e in result.events)


async def test_no_skill_selected_leaves_prompt_unmodified(monkeypatch, tmp_path):
    fake_client = _FakeMCPClient()
    monkeypatch.setattr("agentops.agent.orchestrator.MCPClient", lambda *a, **k: fake_client)
    orchestrator, _ = _build([_final_answer_result()])

    result = await orchestrator.run("Forklar generelt hvad dette repository gør.", tmp_path)

    assert result.skill_selected is None
    assert not any(e.type.value == "skill_selected" for e in result.events)


async def test_memory_retriever_is_called_and_injected_into_prompt(monkeypatch, tmp_path):
    fake_client = _FakeMCPClient()
    monkeypatch.setattr("agentops.agent.orchestrator.MCPClient", lambda *a, **k: fake_client)

    retrieved = [
        MemoryRecord(
            workspace_key="ws",
            category=MemoryCategory.LESSON_LEARNED,
            summary="Sidste gang var fejlen i add().",
            outcome="success",
        )
    ]

    async def fake_retriever(workspace_key: str, query: str):
        return retrieved

    orchestrator, provider = _build([_final_answer_result()], memory_retriever=fake_retriever)

    result = await orchestrator.run("Find og ret fejlen.", tmp_path)

    assert result.memory_hits == 1
    assert "Sidste gang var fejlen i add()" in provider.requests[0].system
    assert any(e.type.value == "memory_retrieved" for e in result.events)


async def test_memory_saver_is_called_on_terminal_completion(monkeypatch, tmp_path):
    fake_client = _FakeMCPClient()
    monkeypatch.setattr("agentops.agent.orchestrator.MCPClient", lambda *a, **k: fake_client)

    saved: list[AgentRunResult] = []

    async def fake_saver(workspace_key: str, task: str, result: AgentRunResult):
        saved.append(result)

    orchestrator, _ = _build([_final_answer_result()], memory_saver=fake_saver)
    result = await orchestrator.run("Find og ret fejlen.", tmp_path)

    assert result.status == TaskStatus.COMPLETED
    assert len(saved) == 1


async def test_memory_saver_is_not_called_while_awaiting_approval(monkeypatch, tmp_path):
    fake_client = _FakeMCPClient()
    monkeypatch.setattr("agentops.agent.orchestrator.MCPClient", lambda *a, **k: fake_client)

    saved: list[AgentRunResult] = []

    async def fake_saver(workspace_key: str, task: str, result: AgentRunResult):
        saved.append(result)

    orchestrator, _ = _build(
        [_tool_use_result("apply_patch", {"diff_text": "..."})], memory_saver=fake_saver
    )
    result = await orchestrator.run("Find og ret fejlen.", tmp_path)

    assert result.status == TaskStatus.AWAITING_APPROVAL
    assert saved == []


async def test_dynamic_tool_discovery_reduces_tools_sent_to_model(monkeypatch, tmp_path):
    fake_client = _FakeMCPClient()
    monkeypatch.setattr("agentops.agent.orchestrator.MCPClient", lambda *a, **k: fake_client)

    settings = Settings(llm_default_provider="test", agent_dynamic_tool_discovery=True)
    orchestrator, provider = _build([_final_answer_result()], settings=settings)

    result = await orchestrator.run("Lav en security review af koden.", tmp_path)

    assert result.tools_available_count == len(_ALL_TOOL_NAMES)
    assert result.tools_discovered_count < len(_ALL_TOOL_NAMES)
    assert len(provider.requests[0].tools) == result.tools_discovered_count
    assert any(e.type.value == "tools_discovered" for e in result.events)
    assert "apply_patch" not in {t.name for t in provider.requests[0].tools}


async def test_tool_discovery_disabled_by_default_sends_all_tools(monkeypatch, tmp_path):
    fake_client = _FakeMCPClient()
    monkeypatch.setattr("agentops.agent.orchestrator.MCPClient", lambda *a, **k: fake_client)
    orchestrator, provider = _build([_final_answer_result()])

    result = await orchestrator.run("Lav en security review af koden.", tmp_path)

    assert result.tools_discovered_count == len(_ALL_TOOL_NAMES)
    assert len(provider.requests[0].tools) == len(_ALL_TOOL_NAMES)


async def test_max_continuous_steps_pauses_and_invokes_checkpoint(monkeypatch, tmp_path):
    fake_client = _FakeMCPClient()
    monkeypatch.setattr("agentops.agent.orchestrator.MCPClient", lambda *a, **k: fake_client)

    orchestrator, _ = _build(
        [
            _tool_use_result("search_code", {"query": "def add"}),
            _tool_use_result("read_file", {"path": "src/calculator.py"}),
        ]
    )

    checkpoints: list[int] = []

    async def on_checkpoint(conversation, events, usage):
        checkpoints.append(len(events))

    result = await orchestrator.run(
        "Find og ret fejlen.", tmp_path, on_checkpoint=on_checkpoint, max_continuous_steps=1
    )

    assert result.status == TaskStatus.PAUSED
    assert len(checkpoints) == 1
    assert any(e.type.value == "task_paused" for e in result.events)
    assert fake_client.calls == [("search_code", {"query": "def add"})]


async def test_resume_propagates_skill_and_tool_discovery_fields(monkeypatch, tmp_path):
    """Regression: resume() tidligere glemte at sætte skill_selected/tools_*_count på
    resultatet — kun _run() gjorde det. En eval-case, der først pauser for
    godkendelse og derefter genoptages, ville derfor altid vise skill_selected=None
    og tools_*_count=0, uanset hvad der reelt blev sendt til modellen."""
    fake_client = _FakeMCPClient()
    monkeypatch.setattr("agentops.agent.orchestrator.MCPClient", lambda *a, **k: fake_client)

    orchestrator, _ = _build(
        [_tool_use_result("apply_patch", {"diff_text": "..."}), _final_answer_result("Løst.")]
    )
    paused = await orchestrator.run("Der er en bug, testen fejler.", tmp_path)
    assert paused.status == TaskStatus.AWAITING_APPROVAL
    assert paused.skill_selected == "debugging"

    final = await orchestrator.resume(
        "Der er en bug, testen fejler.",
        tmp_path,
        paused.conversation_state,
        paused.pending_approval,
        approved=True,
        prior_events=paused.events,
    )

    assert final.skill_selected == "debugging"
    assert final.tools_available_count == len(_ALL_TOOL_NAMES)
    assert final.tools_discovered_count == len(_ALL_TOOL_NAMES)


async def test_resume_without_memory_hits_argument_resets_to_zero_not_carried(
    monkeypatch, tmp_path
):
    """Regression: resume() previously reset memory_hits to its Pydantic default (0)
    unconditionally, silently discarding the count from the initial run() even when
    the caller had it available. Callers MUST pass memory_hits explicitly to carry
    it forward — this test documents that contract by proving the explicit value
    always wins over whatever the AWAITING_APPROVAL result reported."""
    fake_client = _FakeMCPClient()
    monkeypatch.setattr("agentops.agent.orchestrator.MCPClient", lambda *a, **k: fake_client)

    retrieved = [
        MemoryRecord(
            workspace_key="ws",
            category=MemoryCategory.LESSON_LEARNED,
            summary="Tidligere løsning.",
            outcome="success",
        )
    ]

    async def fake_retriever(workspace_key: str, query: str):
        return retrieved

    orchestrator, _ = _build(
        [_tool_use_result("apply_patch", {"diff_text": "..."}), _final_answer_result("Løst.")],
        memory_retriever=fake_retriever,
    )
    paused = await orchestrator.run("Der er en bug, testen fejler.", tmp_path)
    assert paused.memory_hits == 1

    final = await orchestrator.resume(
        "Der er en bug, testen fejler.",
        tmp_path,
        paused.conversation_state,
        paused.pending_approval,
        approved=True,
        prior_events=paused.events,
        memory_hits=paused.memory_hits,
    )

    assert final.memory_hits == 1


async def test_continue_task_resumes_paused_work_to_completion(monkeypatch, tmp_path):
    fake_client = _FakeMCPClient()
    monkeypatch.setattr("agentops.agent.orchestrator.MCPClient", lambda *a, **k: fake_client)

    orchestrator, _ = _build(
        [_tool_use_result("search_code", {"query": "def add"})],
    )
    paused = await orchestrator.run("Find og ret fejlen.", tmp_path, max_continuous_steps=1)
    assert paused.status == TaskStatus.PAUSED

    orchestrator._gateway._providers["test"]._results.append(_final_answer_result("Løst."))
    final = await orchestrator.continue_task(
        "Find og ret fejlen.",
        tmp_path,
        paused.conversation_state,
        prior_events=paused.events,
    )

    assert final.status == TaskStatus.COMPLETED
    assert final.final_answer == "Løst."
