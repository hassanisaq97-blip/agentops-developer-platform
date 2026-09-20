"""Workflow-endpoints: kør et kontrolleret multi-agent workflow (Developer/Test/
Security/Reviewer) på en opgave — se agentops.agent.multi_agent og ADR-0015.

Bevidst et separat router/tabel fra `tasks.py`, ikke et alternativt flag på
samme endpoint — en workflow-kørsel har en anden facon (flere faser, ét
samlet verdict) end en enkelt-agent-opgave."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from agentops.agent.context import ContextStrategy
from agentops.agent.multi_agent import MultiAgentOrchestrator
from agentops.agent.schemas import TaskStatus
from agentops.api.converters import workflow_record_to_response
from agentops.api.dependencies import get_app_settings, get_db_session, get_multi_agent_orchestrator
from agentops.api.repositories import UnknownRepositoryError, resolve_repository
from agentops.api.schemas import ApprovalRequest, CreateWorkflowRequest, WorkflowResponse
from agentops.gateway.schemas import TaskComplexity
from agentops.persistence import workflow_repository
from agentops.settings import Settings

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.post("", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    payload: CreateWorkflowRequest,
    session: Session = Depends(get_db_session),
    orchestrator: MultiAgentOrchestrator = Depends(get_multi_agent_orchestrator),
    settings: Settings = Depends(get_app_settings),
) -> WorkflowResponse:
    try:
        workspace_root = resolve_repository(payload.repository, settings)
    except UnknownRepositoryError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    record = workflow_repository.create_workflow(
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
        )
    except Exception as exc:  # se agentops.api.routers.tasks for samme princip
        record.status = TaskStatus.FAILED.value
        session.flush()
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, f"Workflowet fejlede uventet: {exc}"
        ) from exc

    workflow_repository.apply_workflow_result(session, record, result)
    return workflow_record_to_response(record)


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    workflow_id: uuid.UUID, session: Session = Depends(get_db_session)
) -> WorkflowResponse:
    record = workflow_repository.get_workflow(session, workflow_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow ikke fundet.")
    return workflow_record_to_response(record)


@router.get("", response_model=list[WorkflowResponse])
async def list_workflows(session: Session = Depends(get_db_session)) -> list[WorkflowResponse]:
    return [workflow_record_to_response(r) for r in workflow_repository.list_workflows(session)]


@router.post("/{workflow_id}/approve", response_model=WorkflowResponse)
async def approve_workflow(
    workflow_id: uuid.UUID,
    payload: ApprovalRequest,
    session: Session = Depends(get_db_session),
    orchestrator: MultiAgentOrchestrator = Depends(get_multi_agent_orchestrator),
) -> WorkflowResponse:
    record = workflow_repository.get_workflow(session, workflow_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow ikke fundet.")
    if not workflow_repository.is_resumable(record):
        raise HTTPException(status.HTTP_409_CONFLICT, "Workflowet afventer ikke godkendelse.")

    pending = workflow_repository.pending_approval_from_record(record)
    conversation = workflow_repository.developer_conversation_from_record(record)
    events = workflow_repository.developer_events_from_record(record)

    try:
        result = await orchestrator.resume_after_approval(
            record.description,
            Path(record.workspace_root),
            conversation,
            pending,
            approved=payload.approved,
            context_strategy=ContextStrategy(record.context_strategy),
            complexity=TaskComplexity(record.complexity),
            developer_events=events,
            memory_hits=record.memory_hits,
        )
    except Exception as exc:
        record.status = TaskStatus.FAILED.value
        session.flush()
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, f"Workflowet fejlede uventet: {exc}"
        ) from exc

    workflow_repository.apply_workflow_result(session, record, result)
    return workflow_record_to_response(record)
