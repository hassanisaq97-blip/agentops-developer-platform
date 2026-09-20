"""Oversættelse mellem `AgentRunResult` (Pydantic, i-memory) og `TaskRecord` (SQLAlchemy, persisteret).

Holder API-laget (`agentops.api`) fri af SQLAlchemy-detaljer og agent-laget fri
af databasen — orchestratoren ved intet om persistence.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentops.agent.events import AgentEvent
from agentops.agent.schemas import AgentRunResult, PendingApproval, PendingToolCall, TaskStatus
from agentops.gateway.schemas import Message
from agentops.persistence.models import ApprovalDecision, ApprovalRecord, TaskRecord


def create_task(
    session: Session,
    *,
    description: str,
    context_strategy: str,
    complexity: str,
    workspace_root: str,
) -> TaskRecord:
    record = TaskRecord(
        description=description,
        status="running",
        context_strategy=context_strategy,
        complexity=complexity,
        workspace_root=workspace_root,
    )
    session.add(record)
    session.flush()
    return record


def get_task(session: Session, task_id: uuid.UUID) -> TaskRecord | None:
    return session.get(TaskRecord, task_id)


def list_tasks(session: Session, limit: int = 50) -> list[TaskRecord]:
    stmt = select(TaskRecord).order_by(TaskRecord.created_at.desc()).limit(limit)
    return list(session.scalars(stmt))


def apply_agent_result(session: Session, record: TaskRecord, result: AgentRunResult) -> TaskRecord:
    record.status = result.status.value
    record.final_answer = result.final_answer
    record.provider = result.provider
    record.model = result.model
    record.used_fallback = result.used_fallback
    record.tools_used = result.tools_used
    record.files_examined = result.files_examined
    record.files_changed = result.files_changed
    record.tests_run = result.tests_run
    record.tests_passed = result.tests_passed
    record.tests_failed = result.tests_failed
    record.warnings = result.warnings
    record.conversation_state = [m.model_dump(mode="json") for m in result.conversation_state]
    record.events_json = [e.model_dump(mode="json") for e in result.events]
    record.total_input_tokens = result.total_usage.input_tokens
    record.total_output_tokens = result.total_usage.output_tokens
    record.total_latency_ms = result.total_latency_ms

    if result.pending_approval is not None:
        session.add(
            ApprovalRecord(
                task_id=record.id,
                tool_calls_json=[
                    tc.model_dump(mode="json") for tc in result.pending_approval.tool_calls
                ],
            )
        )
    session.flush()
    return record


def get_pending_approval(session: Session, task_id: uuid.UUID) -> ApprovalRecord | None:
    stmt = (
        select(ApprovalRecord)
        .where(
            ApprovalRecord.task_id == task_id, ApprovalRecord.decision == ApprovalDecision.PENDING
        )
        .order_by(ApprovalRecord.created_at.desc())
    )
    return session.scalars(stmt).first()


def record_approval_decision(
    session: Session, approval: ApprovalRecord, *, approved: bool
) -> ApprovalRecord:
    approval.decision = ApprovalDecision.APPROVED if approved else ApprovalDecision.DENIED
    approval.decided_at = datetime.now(UTC)
    session.flush()
    return approval


def to_pending_approval_schema(approval: ApprovalRecord) -> PendingApproval:
    return PendingApproval(
        tool_calls=[PendingToolCall.model_validate(tc) for tc in approval.tool_calls_json]
    )


def conversation_from_record(record: TaskRecord) -> list[Message]:
    return [Message.model_validate(m) for m in record.conversation_state]


def events_from_record(record: TaskRecord) -> list[AgentEvent]:
    return [AgentEvent.model_validate(e) for e in record.events_json]


def is_resumable(record: TaskRecord) -> bool:
    return record.status == TaskStatus.AWAITING_APPROVAL.value
