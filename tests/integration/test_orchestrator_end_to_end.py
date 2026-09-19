"""End-to-end test: hele den agentiske løkke, over den RIGTIGE MCP-protokol.

Dette er den vigtigste integrationstest i platformen — den beviser hele
kæden: orchestrator -> LLM Gateway (deterministic provider) -> MCP-klient ->
spawnet MCP-server-proces -> WorkspaceSandbox -> et rigtigt git-repository på
disk. Ingen af lagene mockes.
"""

from __future__ import annotations

import subprocess

import pytest

from agentops.agent.context import ContextStrategy
from agentops.agent.orchestrator import AgentOrchestrator
from agentops.agent.schemas import TaskStatus
from agentops.gateway.gateway import LLMGateway
from agentops.gateway.providers.test_provider import DeterministicTestProvider
from agentops.gateway.router import ModelRouter
from agentops.settings import Settings


@pytest.fixture
def buggy_repo(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "calculator.py").write_text(
        "def add(a, b):\n    return a - b\n\n\ndef subtract(a, b):\n    return a - b\n"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_calculator.py").write_text(
        "import sys\nfrom pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))\n"
        "from calculator import add\n\n"
        "def test_add():\n    assert add(2, 3) == 5\n"
    )
    (tmp_path / "README.md").write_text("# Demo\nEn lille regnemaskine.\n")
    (tmp_path / "CLAUDE.md").write_text("Dette er et testrepository for AgentOps.\n")
    for cmd in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "test@example.com"],
        ["git", "config", "user.name", "Test"],
        ["git", "add", "."],
        ["git", "commit", "-q", "-m", "init"],
    ):
        subprocess.run(cmd, cwd=tmp_path, check=True)
    return tmp_path


def _build_orchestrator(auto_approve: bool) -> AgentOrchestrator:
    settings = Settings(llm_default_provider="test", agent_auto_approve_high_risk=auto_approve)
    gateway = LLMGateway(
        {"test": DeterministicTestProvider()}, ModelRouter(settings), fallback_provider=None
    )
    return AgentOrchestrator(gateway, settings)


@pytest.mark.integration
async def test_agent_pauses_for_approval_before_applying_patch(buggy_repo):
    orchestrator = _build_orchestrator(auto_approve=False)
    result = await orchestrator.run(
        "Find årsagen til den fejlende test og foreslå en rettelse.",
        buggy_repo,
        context_strategy=ContextStrategy.TARGETED_MCP,
    )

    assert result.status == TaskStatus.AWAITING_APPROVAL
    assert result.pending_approval is not None
    assert result.pending_approval.tool_name == "apply_patch"
    assert result.pending_approval.risk_level == "high"
    assert "get_repository_status" in result.tools_used
    assert "run_tests" in result.tools_used
    assert "search_code" in result.tools_used
    assert "read_file" in result.tools_used
    # Filen er IKKE ændret endnu, fordi high-risk kald ikke er godkendt.
    assert (buggy_repo / "src" / "calculator.py").read_text().count("a - b") == 2


@pytest.mark.integration
async def test_agent_resumes_after_approval_and_fixes_the_bug(buggy_repo):
    orchestrator = _build_orchestrator(auto_approve=False)
    first = await orchestrator.run(
        "Find årsagen til den fejlende test og foreslå en rettelse.",
        buggy_repo,
        context_strategy=ContextStrategy.TARGETED_MCP,
    )
    assert first.status == TaskStatus.AWAITING_APPROVAL

    final = await orchestrator.resume(
        "Find årsagen til den fejlende test og foreslå en rettelse.",
        buggy_repo,
        first.conversation_state,
        first.pending_approval,
        approved=True,
        prior_events=first.events,
    )

    assert final.status == TaskStatus.COMPLETED
    assert final.tests_passed is not None and final.tests_failed == 0
    assert "src/calculator.py" in final.files_changed
    content = (buggy_repo / "src" / "calculator.py").read_text()
    assert "return a + b" in content


@pytest.mark.integration
async def test_agent_records_denial_without_modifying_the_file(buggy_repo):
    orchestrator = _build_orchestrator(auto_approve=False)
    first = await orchestrator.run(
        "Find og ret fejlen.", buggy_repo, context_strategy=ContextStrategy.TARGETED_MCP
    )

    final = await orchestrator.resume(
        "Find og ret fejlen.",
        buggy_repo,
        first.conversation_state,
        first.pending_approval,
        approved=False,
        prior_events=first.events,
    )

    assert (buggy_repo / "src" / "calculator.py").read_text().count("a - b") == 2
    assert any(e.type.value == "approval_denied" for e in final.events)


@pytest.mark.integration
async def test_auto_approve_lets_agent_complete_task_in_one_run(buggy_repo):
    orchestrator = _build_orchestrator(auto_approve=True)
    result = await orchestrator.run(
        "Find årsagen til den fejlende test og foreslå en rettelse.",
        buggy_repo,
        context_strategy=ContextStrategy.TARGETED_MCP,
    )

    assert result.status == TaskStatus.COMPLETED
    assert result.tests_passed is not None and result.tests_failed == 0
    assert "src/calculator.py" in result.files_changed


@pytest.mark.integration
async def test_minimal_strategy_has_no_tools_and_completes_immediately(buggy_repo):
    orchestrator = _build_orchestrator(auto_approve=True)
    result = await orchestrator.run(
        "Find årsagen til den fejlende test.", buggy_repo, context_strategy=ContextStrategy.MINIMAL
    )

    assert result.status == TaskStatus.COMPLETED
    assert result.tools_used == []
    assert result.warnings  # advarer om manglende repository-grundlag
