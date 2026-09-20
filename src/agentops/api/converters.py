"""Oversættelse fra SQLAlchemy-modeller/interne schemas til API-response-schemas."""

from __future__ import annotations

from agentops.api.schemas import (
    EvalCaseResultResponse,
    EvalRunResponse,
    PendingApprovalResponse,
    PendingToolCallResponse,
    TaskEventResponse,
    TaskResponse,
    TaskTraceResponse,
)
from agentops.evaluation.schemas import EvalRunSummary
from agentops.persistence import task_repository
from agentops.persistence.models import ApprovalDecision, TaskRecord


def _pending_approval_response(record: TaskRecord) -> PendingApprovalResponse | None:
    pending = next((a for a in record.approvals if a.decision == ApprovalDecision.PENDING), None)
    if pending is None:
        return None
    return PendingApprovalResponse(
        tool_calls=[PendingToolCallResponse.model_validate(tc) for tc in pending.tool_calls_json]
    )


def task_record_to_response(record: TaskRecord) -> TaskResponse:
    pending = _pending_approval_response(record)
    return TaskResponse(
        id=record.id,
        description=record.description,
        status=record.status,
        context_strategy=record.context_strategy,
        complexity=record.complexity,
        final_answer=record.final_answer,
        provider=record.provider,
        model=record.model,
        used_fallback=record.used_fallback,
        tools_used=record.tools_used,
        files_examined=record.files_examined,
        files_changed=record.files_changed,
        tests_run=record.tests_run,
        tests_passed=record.tests_passed,
        tests_failed=record.tests_failed,
        warnings=record.warnings,
        pending_approval=pending,
        total_input_tokens=record.total_input_tokens,
        total_output_tokens=record.total_output_tokens,
        total_latency_ms=record.total_latency_ms,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def task_record_to_trace_response(record: TaskRecord) -> TaskTraceResponse:
    events = task_repository.events_from_record(record)
    return TaskTraceResponse(
        task_id=record.id,
        events=[
            TaskEventResponse(
                step=e.step,
                type=e.type.value,
                timestamp=e.timestamp,
                tool_name=e.tool_name,
                arguments=e.arguments,
                result_summary=e.result_summary,
                risk_level=e.risk_level.value if e.risk_level else None,
                rationale=e.rationale,
            )
            for e in events
        ],
    )


def eval_summary_to_response(summary: EvalRunSummary) -> EvalRunResponse:
    return EvalRunResponse(
        run_id=summary.run_id,
        provider=summary.provider,
        started_at=summary.started_at,
        finished_at=summary.finished_at,
        success_rate=summary.success_rate,
        expectation_match_rate=summary.expectation_match_rate,
        average_tool_calls=summary.average_tool_calls,
        case_results=[
            EvalCaseResultResponse(
                case_id=r.case_id,
                fixture=r.fixture,
                success=r.metrics.success,
                expected_success=r.expected_success,
                matched_expectation=r.matched_expectation,
                tests_passed=r.metrics.tests_passed,
                tests_failed=r.metrics.tests_failed,
                total_tool_calls=r.metrics.total_tool_calls,
                files_changed_count=r.metrics.files_changed_count,
            )
            for r in summary.case_results
        ],
    )
