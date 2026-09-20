"""Strukturerede, observerbare agent-events.

Vi eksponerer bevidst IKKE modellens rå chain-of-thought. I stedet logger vi
hvert trin som et struktureret event: hvilket tool blev valgt, med hvilke
(redactede) argumenter, hvad resultatet var, og — hvis modellen gav en kort
tekstforklaring sammen med tool-kaldet — den forklaring, som en gennemsigtig
"rationale"-tekst. Det er disse events, en bruger ser i `/tasks/{id}/trace`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from agentops.agent.risk import RiskLevel


class AgentEventType(StrEnum):
    TASK_STARTED = "task_started"
    MEMORY_RETRIEVED = "memory_retrieved"
    SKILL_SELECTED = "skill_selected"
    TOOLS_DISCOVERED = "tools_discovered"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TOOL_ERROR = "tool_error"
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_DENIED = "approval_denied"
    CHECKPOINT_SAVED = "checkpoint_saved"
    TASK_PAUSED = "task_paused"
    FINAL_ANSWER = "final_answer"
    MAX_STEPS_REACHED = "max_steps_reached"


class AgentEvent(BaseModel):
    step: int
    type: AgentEventType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    tool_name: str | None = None
    tool_call_id: str | None = None
    """Bruges til at koble et TOOL_CALL-event sammen med sit senere TOOL_RESULT/APPROVAL-event,
    selv når en godkendelsespause ligger imellem dem."""
    arguments: dict | None = None
    """Redacted før dette objekt oprettes — se agentops.security.secrets.redact_mapping."""
    result_summary: str | None = None
    risk_level: RiskLevel | None = None
    rationale: str | None = None
    """Modellens egen korte tekst ledsagende tool-kaldet — ikke skjult ræsonnement, kun det den eksplicit sagde."""
