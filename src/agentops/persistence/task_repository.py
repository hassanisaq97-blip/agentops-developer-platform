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
    record.memory_hits = result.memory_hits
    record.skill_selected = result.skill_selected
    record.tools_available_count = result.tools_available_count
    record.tools_discovered_count = result.tools_discovered_count
    record.agent_handoffs = result.agent_handoffs

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


def is_continuable(record: TaskRecord) -> bool:
    """En PAUSED opgave (checkpoint-baseret, se ADR-0014) — adskilt fra `is_resumable`,
    som gælder en godkendelsesbeslutning."""
    return record.status == TaskStatus.PAUSED.value


def checkpoint_progress(
    session: Session,
    record: TaskRecord,
    *,
    conversation: list[Message],
    events: list[AgentEvent],
    input_tokens: int,
    output_tokens: int,
) -> None:
    """Skriver løbende fremskridt UNDER en kørsel og committer det STRAKS — ikke kun
    ved kørslens afslutning. Det er selve pointen: hvis processen dør midt i en lang
    opgave, overlever det seneste checkpoint, og opgaven kan gendannes derfra (se
    `recover_interrupted_tasks` og docs/adr/0014-long-running-agents.md)."""
    record.conversation_state = [m.model_dump(mode="json") for m in conversation]
    record.events_json = [e.model_dump(mode="json") for e in events]
    record.total_input_tokens = input_tokens
    record.total_output_tokens = output_tokens
    session.flush()
    session.commit()


def recover_interrupted_tasks(session: Session) -> list[TaskRecord]:
    """Køres ved API-opstart. En opgave, der stadig står som 'running', betyder at
    processen blev lukket ned, mens den kørte — ingen ren afslutning nåede at skrive
    et terminalt resultat. Vi GENOPTAGER ALDRIG automatisk (ville betyde ukontrollerede
    LLM/tool-kald uden opsyn ved opstart); vi markerer den i stedet klart, så et
    menneske/en efterfølgende kaldende kan vælge at fortsætte den eksplicit."""
    stmt = select(TaskRecord).where(TaskRecord.status == "running")
    affected = []
    for record in session.scalars(stmt):
        if record.conversation_state:
            record.status = TaskStatus.PAUSED.value
            record.warnings = [
                *record.warnings,
                "Gendannet efter uventet nedlukning af API'et — kan genoptages via "
                "POST /tasks/{id}/continue.",
            ]
        else:
            record.status = TaskStatus.FAILED.value
            record.warnings = [
                *record.warnings,
                "Ingen checkpoint blev nået, før API'et lukkede ned uventet.",
            ]
        affected.append(record)
    session.flush()
    session.commit()
    return affected
