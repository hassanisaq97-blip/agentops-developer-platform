"""Oversættelse mellem `MultiAgentWorkflowResult` (Pydantic, i-memory) og
`WorkflowRecord` (SQLAlchemy, persisteret) — samme mønster som
`agentops.persistence.task_repository`, for en separat ressource."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentops.agent.events import AgentEvent
from agentops.agent.multi_agent import MultiAgentWorkflowResult
from agentops.agent.schemas import PendingApproval, PendingToolCall, TaskStatus
from agentops.gateway.schemas import Message
from agentops.persistence.models import WorkflowRecord


def create_workflow(
    session: Session,
    *,
    description: str,
    context_strategy: str,
    complexity: str,
    workspace_root: str,
) -> WorkflowRecord:
    record = WorkflowRecord(
        description=description,
        status="running",
        context_strategy=context_strategy,
        complexity=complexity,
        workspace_root=workspace_root,
    )
    session.add(record)
    session.flush()
    return record


def get_workflow(session: Session, workflow_id: uuid.UUID) -> WorkflowRecord | None:
    return session.get(WorkflowRecord, workflow_id)


def list_workflows(session: Session, limit: int = 50) -> list[WorkflowRecord]:
    stmt = select(WorkflowRecord).order_by(WorkflowRecord.created_at.desc()).limit(limit)
    return list(session.scalars(stmt))


def apply_workflow_result(
    session: Session, record: WorkflowRecord, result: MultiAgentWorkflowResult
) -> WorkflowRecord:
    record.status = result.status.value
    record.phases_json = [p.model_dump(mode="json") for p in result.phases]
    record.final_verdict = result.final_verdict
    record.files_changed = result.files_changed
    record.tests_passed = result.tests_passed
    record.tests_failed = result.tests_failed
    record.agent_handoffs = result.agent_handoffs
    record.total_input_tokens = result.total_usage.input_tokens
    record.total_output_tokens = result.total_usage.output_tokens
    record.memory_hits = result.memory_hits
    record.developer_conversation_state = [
        m.model_dump(mode="json") for m in result.developer_conversation_state
    ]
    record.developer_events_json = [e.model_dump(mode="json") for e in result.developer_events]
    record.pending_approval_json = (
        [tc.model_dump(mode="json") for tc in result.pending_approval.tool_calls]
        if result.pending_approval is not None
        else None
    )
    session.flush()
    return record


def is_resumable(record: WorkflowRecord) -> bool:
    return record.status == TaskStatus.AWAITING_APPROVAL.value


def pending_approval_from_record(record: WorkflowRecord) -> PendingApproval:
    assert record.pending_approval_json is not None
    return PendingApproval(
        tool_calls=[PendingToolCall.model_validate(tc) for tc in record.pending_approval_json]
    )


def developer_conversation_from_record(record: WorkflowRecord) -> list[Message]:
    return [Message.model_validate(m) for m in record.developer_conversation_state]


def developer_events_from_record(record: WorkflowRecord) -> list[AgentEvent]:
    return [AgentEvent.model_validate(e) for e in record.developer_events_json]
