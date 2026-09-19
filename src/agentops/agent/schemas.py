from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from agentops.agent.events import AgentEvent
from agentops.agent.risk import RiskLevel
from agentops.gateway.schemas import Message, TokenUsage


class TaskStatus(StrEnum):
    COMPLETED = "completed"
    AWAITING_APPROVAL = "awaiting_approval"
    FAILED = "failed"
    MAX_STEPS_REACHED = "max_steps_reached"


class PendingApproval(BaseModel):
    tool_name: str
    arguments: dict
    risk_level: RiskLevel


class AgentRunResult(BaseModel):
    """Det strukturerede resultat af én agent-kørsel (eller ét trin frem til en godkendelsespause).

    Dette er, hvad `/tasks/{id}` og `/tasks/{id}/trace` bygger deres svar på —
    ikke rå LLM-output.
    """

    status: TaskStatus
    task_summary: str
    final_answer: str | None = None
    tools_used: list[str] = Field(default_factory=list)
    files_examined: list[str] = Field(default_factory=list)
    files_changed: list[str] = Field(default_factory=list)
    tests_run: bool = False
    tests_passed: int | None = None
    tests_failed: int | None = None
    warnings: list[str] = Field(default_factory=list)
    events: list[AgentEvent] = Field(default_factory=list)
    conversation_state: list[Message] = Field(default_factory=list)
    """Serialiserbar samtaletilstand — bruges til at genoptage kørslen efter en godkendelse."""
    pending_approval: PendingApproval | None = None
    total_tool_calls: int = 0
    total_usage: TokenUsage = Field(default_factory=TokenUsage)
    total_latency_ms: float = 0.0
    provider: str | None = None
    model: str | None = None
    used_fallback: bool = False
