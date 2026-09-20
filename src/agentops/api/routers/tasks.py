"""Task-endpoints: opret en agentopgave, se dens status/trace, og godkend/afvis high-risk handlinger."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from agentops.agent.context import ContextStrategy
from agentops.agent.events import AgentEvent
from agentops.agent.orchestrator import AgentOrchestrator, OnCheckpoint
from agentops.agent.schemas import TaskStatus
from agentops.api.converters import task_record_to_response, task_record_to_trace_response
from agentops.api.dependencies import get_app_settings, get_db_session, get_orchestrator
from agentops.api.repositories import UnknownRepositoryError, resolve_repository
from agentops.api.schemas import ApprovalRequest, CreateTaskRequest, TaskResponse, TaskTraceResponse
from agentops.gateway.schemas import Message, TaskComplexity
from agentops.persistence import task_repository
from agentops.persistence.models import TaskRecord
from agentops.settings import Settings

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _make_checkpoint_callback(session: Session, record: TaskRecord) -> OnCheckpoint:
    """Bygger en `on_checkpoint`-callback bundet til DENNE requests session/record —
    holder orchestratoren fri af SQLAlchemy, se agentops.memory.integration for samme
    mønster. Hvert kald COMMITTER straks (se task_repository.checkpoint_progress),
    så fremskridt overlever selv en uventet nedlukning midt i en lang kørsel."""

    async def on_checkpoint(conversation: list[Message], events: list[AgentEvent], usage) -> None:
        task_repository.checkpoint_progress(
            session,
            record,
            conversation=conversation,
            events=events,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )

    return on_checkpoint


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: CreateTaskRequest,
    session: Session = Depends(get_db_session),
    orchestrator: AgentOrchestrator = Depends(get_orchestrator),
    settings: Settings = Depends(get_app_settings),
) -> TaskResponse:
    try:
        workspace_root = resolve_repository(payload.repository, settings)
    except UnknownRepositoryError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    record = task_repository.create_task(
        session,
        description=payload.description,
        context_strategy=payload.context_strategy.value,
        complexity=payload.complexity.value,
        workspace_root=str(workspace_root),
    )

    try:
        result = await orchestrator.run(
            payload.description,
            workspace_root,
            context_strategy=payload.context_strategy,
            complexity=payload.complexity,
            on_checkpoint=_make_checkpoint_callback(session, record),
            max_continuous_steps=settings.agent_checkpoint_every_n_steps or None,
        )
    except Exception as exc:  # bevidst bredt: en fejlet agent-kørsel skal give et forklaret task-resultat, ikke en 500'er
        record.status = TaskStatus.FAILED.value
        record.warnings = [f"Agent-kørslen fejlede uventet: {exc}"]
        session.flush()
        return task_record_to_response(record)

    task_repository.apply_agent_result(session, record, result)
    return task_record_to_response(record)


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(task_id: uuid.UUID, session: Session = Depends(get_db_session)) -> TaskResponse:
    record = task_repository.get_task(session, task_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Opgave ikke fundet.")
    return task_record_to_response(record)


@router.get("", response_model=list[TaskResponse])
async def list_tasks(session: Session = Depends(get_db_session)) -> list[TaskResponse]:
    return [task_record_to_response(r) for r in task_repository.list_tasks(session)]


@router.get("/{task_id}/trace", response_model=TaskTraceResponse)
async def get_task_trace(
    task_id: uuid.UUID, session: Session = Depends(get_db_session)
) -> TaskTraceResponse:
    record = task_repository.get_task(session, task_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Opgave ikke fundet.")
    return task_record_to_trace_response(record)


@router.post("/{task_id}/approve", response_model=TaskResponse)
async def approve_task(
    task_id: uuid.UUID,
    payload: ApprovalRequest,
    session: Session = Depends(get_db_session),
    orchestrator: AgentOrchestrator = Depends(get_orchestrator),
    settings: Settings = Depends(get_app_settings),
) -> TaskResponse:
    record = task_repository.get_task(session, task_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Opgave ikke fundet.")
    if not task_repository.is_resumable(record):
        raise HTTPException(status.HTTP_409_CONFLICT, "Opgaven afventer ikke godkendelse.")

    pending = task_repository.get_pending_approval(session, task_id)
    if pending is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Ingen afventende godkendelse fundet for denne opgave."
        )

    task_repository.record_approval_decision(session, pending, approved=payload.approved)
    pending_schema = task_repository.to_pending_approval_schema(pending)
    conversation = task_repository.conversation_from_record(record)
    prior_events = task_repository.events_from_record(record)

    try:
        result = await orchestrator.resume(
            record.description,
            Path(record.workspace_root),
            conversation,
            pending_schema,
            approved=payload.approved,
            context_strategy=ContextStrategy(record.context_strategy),
            complexity=TaskComplexity(record.complexity),
            prior_events=prior_events,
            on_checkpoint=_make_checkpoint_callback(session, record),
            max_continuous_steps=settings.agent_checkpoint_every_n_steps or None,
        )
    except Exception as exc:  # se create_task ovenfor: en fejlet genoptagelse skal give et forklaret task-resultat, ikke en 500'er
        record.status = TaskStatus.FAILED.value
        record.warnings = [f"Agent-kørslen fejlede uventet under genoptagelse: {exc}"]
        session.flush()
        return task_record_to_response(record)

    task_repository.apply_agent_result(session, record, result)
    return task_record_to_response(record)


@router.post("/{task_id}/continue", response_model=TaskResponse)
async def continue_task(
    task_id: uuid.UUID,
    session: Session = Depends(get_db_session),
    orchestrator: AgentOrchestrator = Depends(get_orchestrator),
    settings: Settings = Depends(get_app_settings),
) -> TaskResponse:
    """Genoptager en PAUSED (checkpoint-baseret) opgave — se ADR-0014. Adskilt fra
    `/approve`, som gælder en menneskelig godkendelses-BESLUTNING for et HIGH-risk
    tool call, ikke bare 'fortsæt en langvarig opgave' eller 'gendan efter en
    uventet nedlukning'."""
    record = task_repository.get_task(session, task_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Opgave ikke fundet.")
    if not task_repository.is_continuable(record):
        raise HTTPException(status.HTTP_409_CONFLICT, "Opgaven er ikke sat på pause.")

    conversation = task_repository.conversation_from_record(record)
    prior_events = task_repository.events_from_record(record)

    try:
        result = await orchestrator.continue_task(
            record.description,
            Path(record.workspace_root),
            conversation,
            context_strategy=ContextStrategy(record.context_strategy),
            complexity=TaskComplexity(record.complexity),
            prior_events=prior_events,
            on_checkpoint=_make_checkpoint_callback(session, record),
            max_continuous_steps=settings.agent_checkpoint_every_n_steps or None,
        )
    except Exception as exc:  # se create_task ovenfor: samme princip for genoptagelse
        record.status = TaskStatus.FAILED.value
        record.warnings = [f"Agent-kørslen fejlede uventet under fortsættelse: {exc}"]
        session.flush()
        return task_record_to_response(record)

    task_repository.apply_agent_result(session, record, result)
    return task_record_to_response(record)
