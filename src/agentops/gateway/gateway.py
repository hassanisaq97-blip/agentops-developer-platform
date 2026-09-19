"""LLM Gateway: det eneste sted i platformen, der kalder ud til en LLM-provider.

Ansvar (jf. arkitekturbeslutning ADR-0002):
- provider-abstraktion (agent-koden kender aldrig til Anthropic/OpenAI-specifikke typer)
- model routing (via ModelRouter)
- retries med backoff for forbigående fejl
- normaliseret fejlhåndtering (ProviderError/AllProvidersFailedError)
- fallback til en sekundær provider, hvis den primære fejler efter retries
- indsamling af latency og token usage til observability-laget
"""

from __future__ import annotations

import logging

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from agentops.gateway.base import LLMProvider
from agentops.gateway.errors import AllProvidersFailedError, ProviderError, UnknownProviderError
from agentops.gateway.router import ModelRoute, ModelRouter
from agentops.gateway.schemas import CompletionRequest, CompletionResult
from agentops.observability.tracing import SpanType, mlflow
from agentops.security.secrets import redact_mapping

logger = logging.getLogger(__name__)


class LLMGateway:
    def __init__(
        self,
        providers: dict[str, LLMProvider],
        router: ModelRouter,
        *,
        max_retries: int = 2,
        fallback_provider: str | None = "test",
    ):
        if not providers:
            raise ValueError("LLMGateway kræver mindst én registreret provider.")
        self._providers = providers
        self._router = router
        self._max_retries = max_retries
        self._fallback_provider = fallback_provider if fallback_provider in providers else None

    def complete(self, request: CompletionRequest) -> CompletionResult:
        route = self._router.resolve(request)
        provider = self._get_provider(route.provider)

        with mlflow.start_span(name=f"llm_call:{route.provider}", span_type=SpanType.LLM) as span:
            span.set_inputs(
                {
                    "provider": route.provider,
                    "model": route.model,
                    "complexity": request.complexity.value,
                    "num_messages": len(request.messages),
                    "num_tools": len(request.tools),
                }
            )
            try:
                result = self._complete_with_fallback(request, route, provider)
            except (ProviderError, AllProvidersFailedError) as exc:
                span.set_outputs({"error": str(exc)})
                raise
            span.set_outputs(
                {
                    "stop_reason": result.stop_reason.value,
                    "input_tokens": result.usage.input_tokens,
                    "output_tokens": result.usage.output_tokens,
                    "latency_ms": result.latency_ms,
                    "used_fallback": result.used_fallback,
                    "tool_calls": redact_mapping(
                        {"calls": [tc.model_dump() for tc in result.message.tool_calls]}
                    ),
                }
            )
            return result

    def _complete_with_fallback(
        self, request: CompletionRequest, route: ModelRoute, provider: LLMProvider
    ) -> CompletionResult:
        try:
            return self._call_with_retry(provider, request, route.model)
        except ProviderError as primary_error:
            if self._fallback_provider and self._fallback_provider != route.provider:
                logger.warning(
                    "provider_fallback_triggered",
                    extra={
                        "failed_provider": route.provider,
                        "fallback_provider": self._fallback_provider,
                    },
                )
                fallback = self._providers[self._fallback_provider]
                try:
                    result = self._call_with_retry(fallback, request, "deterministic-v1")
                    result.used_fallback = True
                    return result
                except ProviderError as fallback_error:
                    raise AllProvidersFailedError(
                        f"Primær provider '{route.provider}' fejlede ({primary_error}); "
                        f"fallback '{self._fallback_provider}' fejlede også ({fallback_error})."
                    ) from fallback_error
            raise

    def _get_provider(self, name: str) -> LLMProvider:
        if name not in self._providers:
            raise UnknownProviderError(
                f"Provider '{name}' er ikke registreret. Kendte: {list(self._providers)}"
            )
        return self._providers[name]

    def _call_with_retry(
        self, provider: LLMProvider, request: CompletionRequest, model: str
    ) -> CompletionResult:
        @retry(
            retry=retry_if_exception_type(ProviderError),
            stop=stop_after_attempt(self._max_retries + 1),
            wait=wait_exponential(multiplier=0.5, min=0.5, max=4),
            reraise=True,
        )
        def _call() -> CompletionResult:
            return provider.complete(request, model=model)

        return _call()
