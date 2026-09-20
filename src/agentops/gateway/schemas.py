"""Provider-uafhængige schemas for LLM Gateway'et.

Alle providers (Anthropic, OpenAI, test) oversætter til/fra disse typer, så
resten af platformen (agent orchestrator, MLflow-tracing, evals) aldrig
behøver kende til en specifik providers native format.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class ChatRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class TaskComplexity(StrEnum):
    """Bruges af model-routeren til at vælge mellem en hurtig/billig og en stærk model."""

    SIMPLE = "simple"
    COMPLEX = "complex"


class ToolDefinition(BaseModel):
    name: str
    description: str
    input_schema: dict = Field(default_factory=dict)


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict = Field(default_factory=dict)


class Message(BaseModel):
    role: ChatRole
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None
    """Sat når role == TOOL: hvilket tool call dette er et resultat af."""
    name: str | None = None
    """Sat når role == TOOL: navnet på det tool, der blev kaldt (til logging/routing)."""
    raw_provider_blocks: list[dict] | None = None
    """Provider-specifikke content blocks bevaret verbatim (fx Anthropic thinking-blocks
    med deres signatur). Bruges KUN når beskeden echoes tilbage til den SAMME provider,
    der producerede den — nødvendigt for korrekt adaptive-thinking-kontinuitet på
    Claude Opus 5/Sonnet 5. Andre providers ignorerer feltet."""


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class CompletionRequest(BaseModel):
    messages: list[Message]
    tools: list[ToolDefinition] = Field(default_factory=list)
    system: str | None = None
    max_tokens: int = 2048
    temperature: float = 0.0
    complexity: TaskComplexity = TaskComplexity.SIMPLE
    provider: str | None = None
    """Eksplicit provider-navn. Hvis None, afgøres den af ModelRouter."""
    model: str | None = None
    """Eksplicit model. Hvis None, afgøres den af ModelRouter ud fra `complexity`."""


class StopReason(StrEnum):
    END_TURN = "end_turn"
    TOOL_USE = "tool_use"
    MAX_TOKENS = "max_tokens"
    ERROR = "error"


class CompletionResult(BaseModel):
    message: Message
    stop_reason: StopReason
    usage: TokenUsage
    latency_ms: float
    provider: str
    model: str
    used_fallback: bool = False
    """True hvis den primære provider fejlede og gatewayen faldt tilbage til en anden."""
