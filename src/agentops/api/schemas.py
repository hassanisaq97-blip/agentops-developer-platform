"""Pydantic request/response-schemas for FastAPI-laget.

Adskilt fra de interne domæne-schemas i `agentops.agent.schemas` /
`agentops.gateway.schemas`, så vi kan ændre den offentlige API-kontrakt uden
at røre agent-logikken, og omvendt.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from agentops.agent.context import ContextStrategy
from agentops.agent.risk import RiskLevel
from agentops.gateway.schemas import TaskComplexity


class CreateTaskRequest(BaseModel):
    description: str = Field(
        ..., min_length=1, max_length=4000, description="Softwareudviklingsopgaven til agenten."
    )
    repository: str = Field(
        default="demo",
        description="Navnet på et konfigureret, allowlisted repository — ikke en fri filsti (se docs/security.md).",
    )
    context_strategy: ContextStrategy = ContextStrategy.TARGETED_MCP
    complexity: TaskComplexity = TaskComplexity.SIMPLE


class PendingToolCallResponse(BaseModel):
    id: str
    tool_name: str
    arguments: dict
    risk_level: RiskLevel


class PendingApprovalResponse(BaseModel):
    """Alle tool calls fra samme model-tur, afventende én samlet godkendelse — se
    agentops.agent.schemas.PendingApproval."""

    tool_calls: list[PendingToolCallResponse]


class TaskResponse(BaseModel):
    id: uuid.UUID
    description: str
    status: str
    context_strategy: str
    complexity: str
    final_answer: str | None
    provider: str | None
    model: str | None
    used_fallback: bool
    tools_used: list[str]
    files_examined: list[str]
    files_changed: list[str]
    tests_run: bool
    tests_passed: int | None
    tests_failed: int | None
    warnings: list[str]
    pending_approval: PendingApprovalResponse | None
    total_input_tokens: int
    total_output_tokens: int
    total_latency_ms: float
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TaskEventResponse(BaseModel):
    step: int
    type: str
    timestamp: datetime
    tool_name: str | None
    arguments: dict | None
    result_summary: str | None
    risk_level: str | None
    rationale: str | None


class TaskTraceResponse(BaseModel):
    task_id: uuid.UUID
    events: list[TaskEventResponse]


class ApprovalRequest(BaseModel):
    approved: bool


class ToolInfo(BaseModel):
    name: str
    description: str
    risk_level: RiskLevel


class EvalCaseResultResponse(BaseModel):
    case_id: str
    fixture: str
    success: bool
    expected_success: bool
    matched_expectation: bool
    tests_passed: int | None
    tests_failed: int | None
    total_tool_calls: int
    files_changed_count: int


class EvalRunResponse(BaseModel):
    run_id: uuid.UUID
    provider: str
    started_at: datetime
    finished_at: datetime | None
    success_rate: float
    expectation_match_rate: float
    average_tool_calls: float
    case_results: list[EvalCaseResultResponse]
