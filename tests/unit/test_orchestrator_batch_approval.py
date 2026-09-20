"""Enhedstests for orchestratorens håndtering af FLERE tool calls i én model-tur.

Anthropic/OpenAI kan returnere flere parallelle tool_use-blocks i ét svar.
`AgentOrchestrator._run_loop` skal (se docs/adr/0011-batch-tool-call-approval.md):
  - lade low/medium-risk tool calls eksekvere direkte, uden mocking af MCP-serveren
    som subprocess — her mockes kun `MCPClient.call_tool`, så testene er hurtige
    unit-tests og ikke kræver en spawnet proces.
  - pausere HELE batchen for godkendelse, hvis mindst ét kald deri er HIGH-risk
    (eller ukendt, som fail-closed behandles som HIGH-risk).
  - aldrig eksekvere noget som helst tool call, før hele batchen er godkendt.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from agentops.agent.orchestrator import AgentOrchestrator
from agentops.agent.risk import RiskLevel
from agentops.agent.schemas import TaskStatus
from agentops.gateway.base import LLMProvider
from agentops.gateway.gateway import LLMGateway
from agentops.gateway.router import ModelRouter
from agentops.gateway.schemas import (
    ChatRole,
    CompletionResult,
    Message,
    StopReason,
    TaskComplexity,
    TokenUsage,
    ToolCall,
    ToolDefinition,
)
from agentops.settings import Settings


class _ScriptedProvider(LLMProvider):
    """Returnerer på forhånd definerede CompletionResults i rækkefølge — bruges
    til deterministisk at simulere en model, der udsender flere tool calls."""

    name = "test"

    def __init__(self, results: list[CompletionResult]):
        self._results = list(results)

    def complete(self, request, *, model):  # noqa: ANN001, ARG002
        return self._results.pop(0)


def _tool_use_result(tool_calls: list[ToolCall]) -> CompletionResult:
    return CompletionResult(
        message=Message(role=ChatRole.ASSISTANT, content=None, tool_calls=tool_calls),
        stop_reason=StopReason.TOOL_USE,
        usage=TokenUsage(input_tokens=10, output_tokens=5),
        latency_ms=1.0,
        provider="test",
        model="deterministic-v1",
    )


def _final_answer_result(text: str) -> CompletionResult:
    return CompletionResult(
        message=Message(role=ChatRole.ASSISTANT, content=text, tool_calls=[]),
        stop_reason=StopReason.END_TURN,
        usage=TokenUsage(input_tokens=5, output_tokens=5),
        latency_ms=1.0,
        provider="test",
        model="deterministic-v1",
    )


def _build_orchestrator(
    results: list[CompletionResult], *, auto_approve: bool
) -> AgentOrchestrator:
    settings = Settings(llm_default_provider="test", agent_auto_approve_high_risk=auto_approve)
    provider = _ScriptedProvider(results)
    gateway = LLMGateway({"test": provider}, ModelRouter(settings), fallback_provider=None)
    return AgentOrchestrator(gateway, settings)


_TOOLS = [
    ToolDefinition(name="read_file", description="Læs en fil."),
    ToolDefinition(name="search_code", description="Søg i koden."),
    ToolDefinition(name="apply_patch", description="Anvend en unified diff."),
]


async def _run_loop_with(orchestrator: AgentOrchestrator, mcp_client) -> object:
    return await orchestrator._run_loop(
        task="Find og ret fejlen.",
        system_prompt="system",
        conversation=[Message(role=ChatRole.USER, content="Find og ret fejlen.")],
        tools=_TOOLS,
        mcp_client=mcp_client,
        complexity=TaskComplexity.SIMPLE,
        events=[],
        approval_decision=None,
    )


async def test_batch_with_a_high_risk_call_pauses_entirely_without_executing_anything():
    tool_calls = [
        ToolCall(id="call_low", name="read_file", arguments={"path": "src/calculator.py"}),
        ToolCall(id="call_high", name="apply_patch", arguments={"diff_text": "..."}),
    ]
    orchestrator = _build_orchestrator([_tool_use_result(tool_calls)], auto_approve=False)
    mcp_client = AsyncMock()

    result = await _run_loop_with(orchestrator, mcp_client)

    assert result.status == TaskStatus.AWAITING_APPROVAL
    assert result.pending_approval is not None
    assert {tc.id for tc in result.pending_approval.tool_calls} == {"call_low", "call_high"}
    risk_by_id = {tc.id: tc.risk_level for tc in result.pending_approval.tool_calls}
    assert risk_by_id["call_low"] == RiskLevel.LOW
    assert risk_by_id["call_high"] == RiskLevel.HIGH
    # Intet er eksekveret endnu — hele batchen afventer én samlet godkendelse.
    mcp_client.call_tool.assert_not_called()


async def test_batch_of_only_low_risk_calls_executes_both_without_approval():
    tool_calls = [
        ToolCall(id="call_1", name="read_file", arguments={"path": "src/calculator.py"}),
        ToolCall(id="call_2", name="search_code", arguments={"query": "def add"}),
    ]
    orchestrator = _build_orchestrator(
        [_tool_use_result(tool_calls), _final_answer_result("Fandt fejlen.")],
        auto_approve=False,
    )
    mcp_client = AsyncMock()
    mcp_client.call_tool = AsyncMock(return_value='{"ok": true}')

    result = await _run_loop_with(orchestrator, mcp_client)

    assert result.status == TaskStatus.COMPLETED
    assert result.pending_approval is None
    assert mcp_client.call_tool.await_count == 2
    called_names = {call.args[0] for call in mcp_client.call_tool.await_args_list}
    assert called_names == {"read_file", "search_code"}


async def test_unknown_tool_name_is_fail_closed_even_with_auto_approve_disabled():
    tool_calls = [ToolCall(id="call_unknown", name="delete_repository", arguments={})]
    orchestrator = _build_orchestrator([_tool_use_result(tool_calls)], auto_approve=False)
    mcp_client = AsyncMock()

    result = await _run_loop_with(orchestrator, mcp_client)

    assert result.status == TaskStatus.AWAITING_APPROVAL
    assert result.pending_approval is not None
    assert result.pending_approval.tool_calls[0].risk_level == RiskLevel.HIGH
    mcp_client.call_tool.assert_not_called()
