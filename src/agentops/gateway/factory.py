"""Bygger en LLMGateway fra Settings — registrerer kun providers, der reelt kan konstrueres.

Anthropic/OpenAI-providers kræver en API-nøgle og springes stiltiende over,
hvis den mangler (i stedet for at fejle ved opstart) — den deterministiske
test-provider er altid tilgængelig og fungerer derfor som et sikkert fallback-net.
"""

from __future__ import annotations

import logging

from agentops.gateway.base import LLMProvider
from agentops.gateway.gateway import LLMGateway
from agentops.gateway.providers.anthropic_provider import AnthropicProvider
from agentops.gateway.providers.openai_provider import OpenAIProvider
from agentops.gateway.providers.test_provider import DeterministicTestProvider
from agentops.gateway.router import ModelRouter
from agentops.settings import Settings

logger = logging.getLogger(__name__)


def build_gateway(settings: Settings) -> LLMGateway:
    providers: dict[str, LLMProvider] = {"test": DeterministicTestProvider()}

    if settings.anthropic_api_key:
        providers["anthropic"] = AnthropicProvider(
            api_key=settings.anthropic_api_key, timeout_seconds=settings.llm_request_timeout_seconds
        )
    if settings.openai_api_key:
        providers["openai"] = OpenAIProvider(
            api_key=settings.openai_api_key, timeout_seconds=settings.llm_request_timeout_seconds
        )

    if settings.llm_default_provider not in providers:
        logger.warning(
            "configured_provider_unavailable_falling_back_to_test",
            extra={"configured_provider": settings.llm_default_provider},
        )
        settings = settings.model_copy(update={"llm_default_provider": "test"})

    router = ModelRouter(settings)
    return LLMGateway(providers, router, max_retries=settings.llm_max_retries)
