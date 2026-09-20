"""Integrationstest for multi-agent workflowet: Developer -> Test -> Security ->
Reviewer, over den RIGTIGE MCP-protokol (samme fixture-mønster som
test_orchestrator_end_to_end.py) — ingen af lagene mockes."""

from __future__ import annotations

import subprocess

import pytest

from agentops.agent.context import ContextStrategy
from agentops.agent.multi_agent import AgentRole, MultiAgentOrchestrator
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
    for cmd in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "test@example.com"],
        ["git", "config", "user.name", "Test"],
        ["git", "add", "."],
        ["git", "commit", "-q", "-m", "init"],
    ):
        subprocess.run(cmd, cwd=tmp_path, check=True)
    return tmp_path


def _build_workflow(auto_approve: bool) -> MultiAgentOrchestrator:
    settings = Settings(llm_default_provider="test", agent_auto_approve_high_risk=auto_approve)
    gateway = LLMGateway(
        {"test": DeterministicTestProvider()}, ModelRouter(settings), fallback_provider=None
    )
    return MultiAgentOrchestrator(gateway, settings)


@pytest.mark.integration
async def test_workflow_pauses_for_developer_approval(buggy_repo):
    workflow = _build_workflow(auto_approve=False)
    result = await workflow.run(
        "Find og ret den fejlende test.", buggy_repo, context_strategy=ContextStrategy.TARGETED_MCP
    )

    assert result.status == TaskStatus.AWAITING_APPROVAL
    assert result.pending_approval is not None
    assert len(result.phases) == 1
    assert result.phases[0].role == AgentRole.DEVELOPER
    assert result.agent_handoffs == 0


@pytest.mark.integration
async def test_workflow_completes_all_four_phases_after_approval(buggy_repo):
    workflow = _build_workflow(auto_approve=False)
    first = await workflow.run(
        "Find og ret den fejlende test.", buggy_repo, context_strategy=ContextStrategy.TARGETED_MCP
    )
    assert first.status == TaskStatus.AWAITING_APPROVAL

    final = await workflow.resume_after_approval(
        "Find og ret den fejlende test.",
        buggy_repo,
        first.developer_conversation_state,
        first.pending_approval,
        approved=True,
        developer_events=first.developer_events,
    )

    assert final.status == TaskStatus.COMPLETED
    roles = [p.role for p in final.phases]
    assert roles == [AgentRole.DEVELOPER, AgentRole.TEST, AgentRole.SECURITY, AgentRole.REVIEWER]
    assert final.agent_handoffs == 4
    assert final.final_verdict == "approved"
    assert final.tests_passed is not None and final.tests_failed == 0
    assert "src/calculator.py" in final.files_changed
    # Sikkerhedsfasen fandt intet mistænkeligt i en simpel sign-fix.
    assert final.phases[2].success is True
    assert final.phases[2].findings == []


@pytest.mark.integration
async def test_workflow_auto_approve_completes_in_one_call(buggy_repo):
    workflow = _build_workflow(auto_approve=True)
    result = await workflow.run(
        "Find og ret den fejlende test.", buggy_repo, context_strategy=ContextStrategy.TARGETED_MCP
    )

    assert result.status == TaskStatus.COMPLETED
    assert result.final_verdict == "approved"
    assert result.agent_handoffs == 4
    assert result.tests_passed is not None and result.tests_failed == 0


@pytest.mark.integration
async def test_workflow_denied_approval_still_completes_but_reviewer_requests_changes(buggy_repo):
    """En afvist høj-risiko handling betyder ikke, at Developer-fasen internt
    fejler (den deterministiske provider fortsætter sin scriptede løkke og
    konkluderer, uden at filen reelt blev ændret) — men Test-fasen opdager, at
    testsuiten stadig fejler, og Reviewer-fasen skal derfor konkludere
    'changes_requested', ikke 'approved'. Se ADR-0015."""
    workflow = _build_workflow(auto_approve=False)
    first = await workflow.run(
        "Find og ret den fejlende test.", buggy_repo, context_strategy=ContextStrategy.TARGETED_MCP
    )

    final = await workflow.resume_after_approval(
        "Find og ret den fejlende test.",
        buggy_repo,
        first.developer_conversation_state,
        first.pending_approval,
        approved=False,
        developer_events=first.developer_events,
    )

    assert (buggy_repo / "src" / "calculator.py").read_text().count("a - b") == 2
    assert final.status == TaskStatus.COMPLETED
    assert final.final_verdict == "changes_requested"
    test_phase = next(p for p in final.phases if p.role == AgentRole.TEST)
    assert test_phase.success is False
