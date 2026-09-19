import pytest

from agentops.gateway.base import LLMProvider
from agentops.gateway.errors import AllProvidersFailedError, ProviderError, UnknownProviderError
from agentops.gateway.gateway import LLMGateway
from agentops.gateway.providers.test_provider import DeterministicTestProvider
from agentops.gateway.router import ModelRoute, ModelRouter
from agentops.gateway.schemas import ChatRole, CompletionRequest, Message, TaskComplexity
from agentops.settings import Settings


class AlwaysFailingProvider(LLMProvider):
    name = "flaky"

    def __init__(self):
        self.call_count = 0

    def complete(self, request, *, model):
        self.call_count += 1
        raise ProviderError(self.name, "simulated outage")


def _simple_request():
    return CompletionRequest(messages=[Message(role=ChatRole.USER, content="hello")])


def test_router_selects_test_provider_by_default():
    settings = Settings(llm_default_provider="test")
    router = ModelRouter(settings)
    route = router.resolve(_simple_request())
    assert route.provider == "test"
    assert route.model == "deterministic-v1"


def test_router_respects_explicit_override():
    settings = Settings(llm_default_provider="test")
    router = ModelRouter(settings)
    request = CompletionRequest(
        messages=[Message(role=ChatRole.USER, content="hi")],
        provider="anthropic",
        model="claude-opus-5",
    )
    route = router.resolve(request)
    assert route == router.resolve(request)
    assert route.provider == "anthropic"
    assert route.model == "claude-opus-5"


def test_router_picks_complex_route_for_complex_tasks():
    settings = Settings(llm_default_provider="test")
    router = ModelRouter(settings)
    request = CompletionRequest(
        messages=[Message(role=ChatRole.USER, content="hi")], complexity=TaskComplexity.COMPLEX
    )
    route = router.resolve(request)
    assert route.provider == "test"


def test_gateway_retries_then_falls_back_to_test_provider():
    flaky = AlwaysFailingProvider()
    test_provider = DeterministicTestProvider()
    settings = Settings(llm_default_provider="flaky")
    router = ModelRouter(settings)
    # Manually inject a route for the flaky provider since it's not in the standard config.
    router._routes[TaskComplexity.SIMPLE] = ModelRoute(provider="flaky", model="v1")

    gateway = LLMGateway(
        {"flaky": flaky, "test": test_provider}, router, max_retries=1, fallback_provider="test"
    )
    result = gateway.complete(_simple_request())

    assert result.used_fallback is True
    assert result.provider == "test"
    assert flaky.call_count == 2  # 1 forsøg + 1 retry før fallback


def test_gateway_propagates_provider_error_without_fallback():
    flaky = AlwaysFailingProvider()
    settings = Settings(llm_default_provider="flaky")
    router = ModelRouter(settings)
    router._routes[TaskComplexity.SIMPLE] = ModelRoute(provider="flaky", model="v1")

    gateway = LLMGateway({"flaky": flaky}, router, max_retries=0, fallback_provider=None)
    with pytest.raises(ProviderError):
        gateway.complete(_simple_request())


def test_gateway_reports_all_providers_failed_when_fallback_also_fails():
    flaky = AlwaysFailingProvider()
    also_flaky = AlwaysFailingProvider()
    also_flaky.name = "test"
    settings = Settings(llm_default_provider="flaky")
    router = ModelRouter(settings)
    router._routes[TaskComplexity.SIMPLE] = ModelRoute(provider="flaky", model="v1")

    gateway = LLMGateway(
        {"flaky": flaky, "test": also_flaky}, router, max_retries=0, fallback_provider="test"
    )
    with pytest.raises(AllProvidersFailedError):
        gateway.complete(_simple_request())


def test_gateway_raises_unknown_provider_error():
    settings = Settings(llm_default_provider="test")
    router = ModelRouter(settings)
    gateway = LLMGateway({"test": DeterministicTestProvider()}, router)
    request = CompletionRequest(
        messages=[Message(role=ChatRole.USER, content="hi")], provider="nonexistent"
    )
    with pytest.raises(UnknownProviderError):
        gateway.complete(request)
