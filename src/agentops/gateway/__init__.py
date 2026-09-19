"""Provider-uafhængig LLM Gateway: routing, retries, fallback og normaliseret fejlhåndtering."""

from agentops.gateway.errors import (
    AllProvidersFailedError,
    LLMGatewayError,
    ProviderError,
    UnknownProviderError,
)
from agentops.gateway.factory import build_gateway
from agentops.gateway.gateway import LLMGateway
from agentops.gateway.router import ModelRoute, ModelRouter
from agentops.gateway.schemas import (
    ChatRole,
    CompletionRequest,
    CompletionResult,
    Message,
    StopReason,
    TaskComplexity,
    TokenUsage,
    ToolCall,
    ToolDefinition,
)

__all__ = [
    "AllProvidersFailedError",
    "ChatRole",
    "CompletionRequest",
    "CompletionResult",
    "LLMGateway",
    "LLMGatewayError",
    "Message",
    "ModelRoute",
    "ModelRouter",
    "ProviderError",
    "StopReason",
    "TaskComplexity",
    "TokenUsage",
    "ToolCall",
    "ToolDefinition",
    "UnknownProviderError",
    "build_gateway",
]
