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
    PAUSED = "paused"
    """Checkpoint-baseret pause for langvarige opgaver (ADR-0014) — IKKE en
    godkendelsespause. Genoptages via `AgentOrchestrator.continue_task()`, ikke
    `resume()`, som er forbeholdt godkendelsesbeslutninger."""


class PendingToolCall(BaseModel):
    """Ét tool call afventende godkendelse — der kan være flere pr. model-tur,
    da Claude/OpenAI kan returnere parallelle tool_use-blocks i samme svar."""

    id: str
    tool_name: str
    arguments: dict
    risk_level: RiskLevel


class PendingApproval(BaseModel):
    """En hel batch af tool calls fra ét model-svar, afventende én samlet
    menneskelig beslutning.

    Alle tool calls fra samme model-tur godkendes/afvises sammen, ikke
    enkeltvis: Anthropic/OpenAI's tool-use-protokol kræver, at ALLE
    tool_use-blocks i en assistant-besked får et tool_result, før samtalen
    kan fortsætte — vi kan derfor ikke eksekvere nogle og lade andre afvente,
    uden at samtalen ender i en ugyldig tilstand. Se docs/adr/0011.
    """

    tool_calls: list[PendingToolCall]

    @property
    def requires_review(self) -> list[PendingToolCall]:
        """De(t) tool call(s), der reelt udløste godkendelseskravet (HIGH risk)."""
        return [tc for tc in self.tool_calls if tc.risk_level == RiskLevel.HIGH]


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
    memory_hits: int = 0
    """Antal relevante tidligere erfaringer hentet ved opgavens start — 0 hvis memory er slået fra."""
    skill_selected: str | None = None
    """Navnet på den skill, der blev valgt til denne opgave — None hvis ingen matchede."""
    tools_available_count: int = 0
    """Antal tools MCP-serveren faktisk stillede til rådighed (før evt. discovery-filtrering)."""
    tools_discovered_count: int = 0
    """Antal tools der faktisk blev sendt til modellen — lig med tools_available_count,
    medmindre dynamisk tool discovery er slået til."""
    agent_handoffs: int = 0
    """Antal overdragelser mellem agenter i et multi-agent workflow — 0 for en enkelt agent."""
