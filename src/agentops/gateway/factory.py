"""Bygger en LLMGateway fra Settings — registrerer kun providers, der reelt kan konstrueres.

Anthropic/OpenAI-providers kræver en API-nøgle og springes stiltiende over,
hvis den mangler (i stedet for at fejle ved opstart).

Fallback-provider ved et RIGTIGT providerudfald (efter retries) er ALDRIG den
deterministiske test-provider her — se ADR-0012 for hvorfor det tidligere var
default i selve `LLMGateway`-klassen, og hvorfor det var en fejl for
produktionskoden at arve den default. I stedet: hvis en anden rigtig provider
er konfigureret, bruges DEN som fallback (et ægte provider-til-provider
failover); ellers er der intet fallback, og et udfald propagerer som en fejl,
som API-laget fanger og markerer opgaven som `FAILED` med en tydelig
begrundelse (se `agentops.api.routers.tasks`) — aldrig som et stiltiende,
scriptet "success".
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

    real_providers = [name for name in providers if name != "test"]
    fallback_provider = next(
        (name for name in real_providers if name != settings.llm_default_provider), None
    )

    router = ModelRouter(settings)
    return LLMGateway(
        providers,
        router,
        max_retries=settings.llm_max_retries,
        fallback_provider=fallback_provider,
    )
