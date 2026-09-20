"""Tester build_gateway()'s fallback-politik — se ADR-0012.

Den deterministiske test-provider må ALDRIG være fallback for en rigtig
providers udfald i produktionskode. build_gateway() er den eneste
konstruktør, FastAPI-appen og scripts/run_evals.py rent faktisk bruger, så
det er her (ikke kun i LLMGateway-klassen selv) politikken skal verificeres.
"""

from __future__ import annotations

from agentops.gateway.factory import build_gateway
from agentops.settings import Settings


def test_no_real_providers_configured_has_no_fallback():
    settings = Settings(llm_default_provider="test", anthropic_api_key="", openai_api_key="")
    gateway = build_gateway(settings)
    assert gateway.fallback_provider is None


def test_single_real_provider_has_no_fallback():
    settings = Settings(
        llm_default_provider="anthropic", anthropic_api_key="sk-fake", openai_api_key=""
    )
    gateway = build_gateway(settings)
    assert gateway.fallback_provider is None


def test_two_real_providers_fall_back_to_each_other():
    settings = Settings(
        llm_default_provider="anthropic", anthropic_api_key="sk-fake", openai_api_key="sk-fake"
    )
    gateway = build_gateway(settings)
    assert gateway.fallback_provider == "openai"

    settings = settings.model_copy(update={"llm_default_provider": "openai"})
    gateway = build_gateway(settings)
    assert gateway.fallback_provider == "anthropic"


def test_missing_configured_provider_falls_back_to_test_provider_as_primary_not_as_fallback():
    """Hvis den KONFIGUREREDE provider slet ikke kan oprettes (ingen nøgle), bliver
    'test' den PRIMÆRE provider (med en logget advarsel) — det er en anden politik
    end fallback ved et RIGTIGT udfald, og skal stadig ikke sætte 'test' som
    fallback_provider."""
    settings = Settings(llm_default_provider="anthropic", anthropic_api_key="", openai_api_key="")
    gateway = build_gateway(settings)
    assert gateway.fallback_provider is None
