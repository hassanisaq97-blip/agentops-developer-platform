"""Evaluation runner: eksekverer benchmark-cases mod en rigtig agent-kørsel.

Kører med automatisk godkendelse af high-risk tool calls, så en hel
evalueringskørsel kan gennemføres unattended — i en rigtig deployment ville
disse handlinger stadig kræve et menneske (se agentops.agent.risk). Dette er
en bevidst afvigelse, dokumenteret her og i docs/experiments/, ikke en
omgåelse af sikkerhedsmodellen i produktion.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path

from agentops.agent.events import AgentEventType
from agentops.agent.orchestrator import AgentOrchestrator
from agentops.agent.schemas import AgentRunResult, TaskStatus
from agentops.evaluation.fixtures import prepare_workspace
from agentops.evaluation.schemas import (
    DeterministicMetrics,
    EvalCase,
    EvalCaseResult,
    EvalRunSummary,
    SuccessCriterion,
)
from agentops.settings import Settings


class EvalRunner:
    def __init__(self, orchestrator: AgentOrchestrator, settings: Settings):
        self._orchestrator = orchestrator
        self._settings = settings

    async def run_case(self, case: EvalCase, *, workdir: Path) -> EvalCaseResult:
        workspace = prepare_workspace(case.fixture, workdir / case.id)
        result = await self._orchestrator.run(
            case.description,
            workspace,
            context_strategy=case.context_strategy,
            complexity=case.complexity,
        )

        # Godkend automatisk, så evalueringen kan afsluttes uden et menneske i loopet.
        guard = 0
        while (
            result.status == TaskStatus.AWAITING_APPROVAL
            and guard < self._settings.agent_max_tool_calls
        ):
            assert result.pending_approval is not None
            result = await self._orchestrator.resume(
                case.description,
                workspace,
                result.conversation_state,
                result.pending_approval,
                approved=True,
                context_strategy=case.context_strategy,
                complexity=case.complexity,
                prior_events=result.events,
            )
            guard += 1

        metrics = self._compute_metrics(case, result)
        return EvalCaseResult(
            case_id=case.id,
            fixture=case.fixture,
            provider=result.provider or "unknown",
            model=result.model or "unknown",
            context_strategy=case.context_strategy.value,
            metrics=metrics,
            expected_success=case.expect_deterministic_provider_to_solve,
            matched_expectation=metrics.success == case.expect_deterministic_provider_to_solve,
        )

    async def run_all(self, cases: list[EvalCase]) -> EvalRunSummary:
        summary = EvalRunSummary(
            provider=self._settings.llm_default_provider,
            model="varies-per-case",
            context_strategy="varies-per-case",
        )
        with tempfile.TemporaryDirectory(prefix="agentops-eval-") as tmp:
            workdir = Path(tmp)
            for case in cases:
                summary.case_results.append(await self.run_case(case, workdir=workdir))

        summary.finished_at = datetime.now(UTC)
        return summary

    @staticmethod
    def _compute_metrics(case: EvalCase, result: AgentRunResult) -> DeterministicMetrics:
        error = None
        if result.status == TaskStatus.FAILED:
            error = "Agent-kørslen fejlede."
        elif result.status == TaskStatus.MAX_STEPS_REACHED:
            error = "Maksimalt antal tool calls nået."

        success = EvalRunner._evaluate_criterion(case, result)
        expected_changes = case.expected_max_changed_files
        unnecessary = max(0, len(result.files_changed) - expected_changes)

        return DeterministicMetrics(
            success=success,
            status=result.status.value,
            tests_run=result.tests_run,
            tests_passed=result.tests_passed,
            tests_failed=result.tests_failed,
            total_tool_calls=result.total_tool_calls,
            files_changed_count=len(result.files_changed),
            unnecessary_files_changed=unnecessary,
            latency_ms=result.total_latency_ms,
            input_tokens=result.total_usage.input_tokens,
            output_tokens=result.total_usage.output_tokens,
            used_fallback=result.used_fallback,
            error=error,
        )

    @staticmethod
    def _evaluate_criterion(case: EvalCase, result: AgentRunResult) -> bool:
        if case.criterion == SuccessCriterion.TESTS_PASS:
            return bool(
                result.tests_run and result.tests_passed is not None and result.tests_failed == 0
            )

        if case.criterion == SuccessCriterion.TOOL_ARGUMENT_CONTAINS:
            target = case.criterion_target or ""
            for event in result.events:
                if event.type == AgentEventType.TOOL_CALL and event.arguments:
                    values = " ".join(str(v) for v in event.arguments.values())
                    if target in values:
                        return True
            return bool(result.final_answer and target in result.final_answer)

        if case.criterion == SuccessCriterion.FILE_READ_BEFORE_ANSWER:
            target = case.criterion_target or ""
            read_step = None
            answer_step = None
            for event in result.events:
                is_matching_read = (
                    event.type == AgentEventType.TOOL_CALL
                    and event.tool_name == "read_file"
                    and event.arguments
                    and event.arguments.get("path") == target
                )
                if is_matching_read:
                    read_step = event.step
                if event.type == AgentEventType.FINAL_ANSWER:
                    answer_step = event.step
            return read_step is not None and answer_step is not None and read_step < answer_step

        raise ValueError(f"Ukendt success-kriterium: {case.criterion}")
