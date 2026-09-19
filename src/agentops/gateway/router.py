"""Model routing: afgør hvilken provider + model en request skal sendes til.

Routing er konfigurationsdrevet (via Settings), ikke hardcoded if/else i
forretningslogikken. En kompleks coding-opgave routes til en stærkere model;
en simpel opgave (fx klassificering af risikoniveau) kan routes til en
billigere/hurtigere model — begge inden for samme provider, medmindre andet
angives eksplicit på requesten.
"""

from __future__ import annotations

from dataclasses import dataclass

from agentops.gateway.schemas import CompletionRequest, TaskComplexity
from agentops.settings import Settings


@dataclass(frozen=True)
class ModelRoute:
    provider: str
    model: str


class ModelRouter:
    def __init__(self, settings: Settings):
        provider = settings.llm_default_provider
        model_by_provider_and_complexity = {
            ("anthropic", TaskComplexity.SIMPLE): settings.anthropic_fast_model,
            ("anthropic", TaskComplexity.COMPLEX): settings.anthropic_default_model,
            ("openai", TaskComplexity.SIMPLE): settings.openai_fast_model,
            ("openai", TaskComplexity.COMPLEX): settings.openai_default_model,
            ("test", TaskComplexity.SIMPLE): "deterministic-v1",
            ("test", TaskComplexity.COMPLEX): "deterministic-v1",
        }
        self._default_provider = provider
        self._routes = {
            complexity: ModelRoute(
                provider=provider, model=model_by_provider_and_complexity[(provider, complexity)]
            )
            for complexity in TaskComplexity
            if (provider, complexity) in model_by_provider_and_complexity
        }

    def resolve(self, request: CompletionRequest) -> ModelRoute:
        if request.provider and request.model:
            return ModelRoute(provider=request.provider, model=request.model)
        if request.provider:
            fallback_route = self._routes.get(request.complexity)
            model = request.model or (fallback_route.model if fallback_route else "")
            return ModelRoute(provider=request.provider, model=model)

        route = self._routes.get(request.complexity)
        if route is None:
            raise ValueError(
                f"Ingen route konfigureret for provider='{self._default_provider}' og "
                f"complexity='{request.complexity}'."
            )
        if request.model:
            return ModelRoute(provider=route.provider, model=request.model)
        return route
