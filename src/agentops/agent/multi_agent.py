"""Kontrolleret multi-agent workflow: Developer → Test → Security → Reviewer.

Bevidst en FAST, IKKE-CYKLISK pipeline bygget oven på den eksisterende
`AgentOrchestrator` — hver fase er ét afgrænset orchestrator-kald (eller, for
Security-fasen, en deterministisk statisk scanning, se
`agentops.agent.security_scan`). Agenter "snakker" ALDRIG frit med hinanden:
der er ingen løkke, hvor én agents output føres tilbage som et nyt spørgsmål
til en anden — kun én fast rækkefølge, hver med sit eget trin-budget
(`Settings.multi_agent_*_max_steps`), der stopper permanent efter Reviewer.
Det er selve svaret på "agents må ikke bare snakke uendeligt med hinanden":
en pipeline uden tilbageløb kan det strukturelt ikke.

Human-in-the-loop er uændret: Developer-fasen er en almindelig
`AgentOrchestrator`-kørsel, så et HIGH-risk tool call pauser workflowet
PRÆCIS som en normal opgave (`TaskStatus.AWAITING_APPROVAL`) — se
`resume_after_approval()`. Se ADR-0015.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field

from agentops.agent.context import ContextStrategy
from agentops.agent.events import AgentEvent
from agentops.agent.mcp_client import MCPClient
from agentops.agent.orchestrator import AgentOrchestrator, MemoryRetriever, MemorySaver
from agentops.agent.schemas import AgentRunResult, PendingApproval, TaskStatus
from agentops.agent.security_scan import scan_diff_for_issues
from agentops.gateway.gateway import LLMGateway
from agentops.gateway.schemas import Message, TaskComplexity, TokenUsage
from agentops.observability.tracing import SpanType, mlflow
from agentops.settings import Settings


class AgentRole(StrEnum):
    DEVELOPER = "developer"
    TEST = "test"
    SECURITY = "security"
    REVIEWER = "reviewer"


class PhaseResult(BaseModel):
    role: AgentRole
    summary: str
    success: bool
    findings: list[str] = Field(default_factory=list)
    tool_calls: int = 0


class MultiAgentWorkflowResult(BaseModel):
    status: TaskStatus
    task_summary: str
    phases: list[PhaseResult] = Field(default_factory=list)
    final_verdict: str | None = None
    """'approved' | 'changes_requested' — sat af Reviewer-fasen, kun når workflowet er COMPLETED."""
    pending_approval: PendingApproval | None = None
    developer_conversation_state: list[Message] = Field(default_factory=list)
    developer_events: list[AgentEvent] = Field(default_factory=list)
    files_changed: list[str] = Field(default_factory=list)
    tests_passed: int | None = None
    tests_failed: int | None = None
    agent_handoffs: int = 0
    total_usage: TokenUsage = Field(default_factory=TokenUsage)
    total_latency_ms: float = 0.0
    memory_hits: int = 0
    """Fra Developer-fasens INDLEDENDE memory-opslag — se AgentRunResult.memory_hits."""


class MultiAgentOrchestrator:
    def __init__(
        self,
        gateway: LLMGateway,
        settings: Settings,
        *,
        memory_retriever: MemoryRetriever | None = None,
        memory_saver: MemorySaver | None = None,
    ):
        self._gateway = gateway
        self._settings = settings
        self._memory_retriever = memory_retriever
        self._memory_saver = memory_saver

    def _phase_orchestrator(self, max_steps: int) -> AgentOrchestrator:
        phase_settings = self._settings.model_copy(update={"agent_max_tool_calls": max_steps})
        return AgentOrchestrator(
            self._gateway,
            phase_settings,
            memory_retriever=self._memory_retriever,
            memory_saver=self._memory_saver,
        )

    async def run(
        self,
        task: str,
        workspace_root: Path,
        *,
        context_strategy: ContextStrategy = ContextStrategy.TARGETED_MCP,
        complexity: TaskComplexity = TaskComplexity.SIMPLE,
    ) -> MultiAgentWorkflowResult:
        with mlflow.start_span(name="multi_agent_workflow", span_type=SpanType.AGENT) as span:
            span.set_inputs({"task": task})
            dev_orchestrator = self._phase_orchestrator(
                self._settings.multi_agent_developer_max_steps
            )
            with mlflow.start_span(
                name="multi_agent_phase:developer", span_type=SpanType.AGENT
            ) as dev_span:
                dev_result = await dev_orchestrator.run(
                    task, workspace_root, context_strategy=context_strategy, complexity=complexity
                )
                dev_span.set_outputs({"status": dev_result.status.value})

            result = await self._after_developer_phase(
                task, workspace_root, dev_result, context_strategy, complexity
            )
            span.set_outputs({"status": result.status.value, "handoffs": result.agent_handoffs})
            return result

    async def resume_after_approval(
        self,
        task: str,
        workspace_root: Path,
        developer_conversation_state: list[Message],
        pending_approval: PendingApproval,
        *,
        approved: bool,
        context_strategy: ContextStrategy = ContextStrategy.TARGETED_MCP,
        complexity: TaskComplexity = TaskComplexity.SIMPLE,
        developer_events: list[AgentEvent] | None = None,
        memory_hits: int = 0,
    ) -> MultiAgentWorkflowResult:
        """`memory_hits` skal være værdien fra `run()`'s oprindelige resultat — se
        `AgentOrchestrator.resume()`'s tilsvarende parameter."""
        with mlflow.start_span(name="multi_agent_workflow", span_type=SpanType.AGENT) as span:
            span.set_inputs({"task": task, "resumed": True})
            dev_orchestrator = self._phase_orchestrator(
                self._settings.multi_agent_developer_max_steps
            )
            with mlflow.start_span(
                name="multi_agent_phase:developer", span_type=SpanType.AGENT
            ) as dev_span:
                dev_result = await dev_orchestrator.resume(
                    task,
                    workspace_root,
                    developer_conversation_state,
                    pending_approval,
                    approved=approved,
                    memory_hits=memory_hits,
                    context_strategy=context_strategy,
                    complexity=complexity,
                    prior_events=developer_events,
                )
                dev_span.set_outputs({"status": dev_result.status.value})

            result = await self._after_developer_phase(
                task, workspace_root, dev_result, context_strategy, complexity
            )
            span.set_outputs({"status": result.status.value, "handoffs": result.agent_handoffs})
            return result

    async def _after_developer_phase(
        self,
        task: str,
        workspace_root: Path,
        dev_result: AgentRunResult,
        context_strategy: ContextStrategy,
        complexity: TaskComplexity,
    ) -> MultiAgentWorkflowResult:
        if dev_result.status == TaskStatus.AWAITING_APPROVAL:
            return MultiAgentWorkflowResult(
                status=TaskStatus.AWAITING_APPROVAL,
                task_summary=task,
                phases=[
                    PhaseResult(
                        role=AgentRole.DEVELOPER,
                        summary="Afventer menneskelig godkendelse af en foreslået ændring.",
                        success=False,
                        tool_calls=dev_result.total_tool_calls,
                    )
                ],
                pending_approval=dev_result.pending_approval,
                developer_conversation_state=dev_result.conversation_state,
                developer_events=dev_result.events,
                agent_handoffs=0,
                total_usage=dev_result.total_usage,
                total_latency_ms=dev_result.total_latency_ms,
                memory_hits=dev_result.memory_hits,
            )

        developer_phase = PhaseResult(
            role=AgentRole.DEVELOPER,
            summary=dev_result.final_answer or "(intet afsluttende svar fra Developer Agent)",
            success=dev_result.status == TaskStatus.COMPLETED,
            tool_calls=dev_result.total_tool_calls,
        )

        if dev_result.status != TaskStatus.COMPLETED:
            return MultiAgentWorkflowResult(
                status=dev_result.status,
                task_summary=task,
                phases=[developer_phase],
                agent_handoffs=1,
                files_changed=dev_result.files_changed,
                total_usage=dev_result.total_usage,
                total_latency_ms=dev_result.total_latency_ms,
                memory_hits=dev_result.memory_hits,
            )

        phases = [developer_phase]
        handoffs = 1

        test_orchestrator = self._phase_orchestrator(self._settings.multi_agent_test_max_steps)
        with mlflow.start_span(name="multi_agent_phase:test", span_type=SpanType.AGENT) as span:
            test_result = await test_orchestrator.run(
                "Kør testsuiten og rapportér resultatet.",
                workspace_root,
                context_strategy=context_strategy,
                complexity=complexity,
            )
            span.set_outputs(
                {"tests_passed": test_result.tests_passed, "tests_failed": test_result.tests_failed}
            )
        tests_ok = bool(test_result.tests_run and (test_result.tests_failed or 0) == 0)
        phases.append(
            PhaseResult(
                role=AgentRole.TEST,
                summary=(
                    f"{test_result.tests_passed or 0} bestået, "
                    f"{test_result.tests_failed or 0} fejlet."
                    if test_result.tests_run
                    else "Testsuiten blev ikke kørt."
                ),
                success=tests_ok,
                tool_calls=test_result.total_tool_calls,
            )
        )
        handoffs += 1

        with mlflow.start_span(name="multi_agent_phase:security", span_type=SpanType.AGENT) as span:
            findings = await self._run_security_phase(workspace_root)
            span.set_outputs({"findings_count": len(findings)})
        phases.append(
            PhaseResult(
                role=AgentRole.SECURITY,
                summary=(
                    f"{len(findings)} potentielt problem(er) fundet i de ændrede filer."
                    if findings
                    else "Ingen kendte sikkerhedsmønstre fundet i de ændrede filer."
                ),
                success=not findings,
                findings=findings,
            )
        )
        handoffs += 1

        verdict = "approved" if (tests_ok and not findings) else "changes_requested"
        reviewer_summary = self._build_reviewer_summary(phases, verdict)
        phases.append(
            PhaseResult(
                role=AgentRole.REVIEWER, summary=reviewer_summary, success=verdict == "approved"
            )
        )
        handoffs += 1

        total_usage = TokenUsage(
            input_tokens=dev_result.total_usage.input_tokens + test_result.total_usage.input_tokens,
            output_tokens=dev_result.total_usage.output_tokens
            + test_result.total_usage.output_tokens,
        )
        total_latency_ms = dev_result.total_latency_ms + test_result.total_latency_ms

        return MultiAgentWorkflowResult(
            status=TaskStatus.COMPLETED,
            task_summary=task,
            phases=phases,
            final_verdict=verdict,
            files_changed=dev_result.files_changed,
            tests_passed=test_result.tests_passed,
            tests_failed=test_result.tests_failed,
            agent_handoffs=handoffs,
            total_usage=total_usage,
            total_latency_ms=total_latency_ms,
            memory_hits=dev_result.memory_hits,
        )

    async def _run_security_phase(self, workspace_root: Path) -> list[str]:
        async with MCPClient(str(workspace_root), allow_file_edits=False) as mcp_client:
            diff_text = await mcp_client.call_tool("get_git_diff", {})
        return scan_diff_for_issues(diff_text)

    @staticmethod
    def _build_reviewer_summary(phases: list[PhaseResult], verdict: str) -> str:
        if verdict == "approved":
            return (
                "Alle faser bestod: udviklingsændringen blev anvendt, testsuiten består, og "
                "ingen kendte sikkerhedsmønstre blev fundet. Godkendt."
            )
        failing = [p.role.value for p in phases if not p.success]
        return (
            f"Kræver ændringer — følgende fase(r) bestod ikke: {', '.join(failing)}. "
            "Se de enkelte fasers resuméer for detaljer."
        )
