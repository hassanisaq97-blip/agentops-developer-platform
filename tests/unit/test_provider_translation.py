"""Tester provider-oversættelseslogik med mockede SDK-klienter.

Ingen netværkskald: `AnthropicProvider`/`OpenAIProvider` er konstrueret med
en falsk API-nøgle, og den underliggende SDK-klients `.create()`-metode
monkeypatches for at returnere et scriptet svar. Det verificerer vores
oversættelse til/fra provider-formater uden at kræve rigtige credentials.
"""

from __future__ import annotations

from types import SimpleNamespace

from agentops.gateway.providers.anthropic_provider import AnthropicProvider
from agentops.gateway.providers.openai_provider import OpenAIProvider
from agentops.gateway.schemas import (
    ChatRole,
    CompletionRequest,
    Message,
    StopReason,
    ToolDefinition,
)


def test_anthropic_provider_parses_tool_use_response(monkeypatch):
    provider = AnthropicProvider(api_key="fake-key")

    fake_response = SimpleNamespace(
        content=[
            SimpleNamespace(
                type="tool_use", id="call_1", name="search_code", input={"query": "def add"}
            )
        ],
        stop_reason="tool_use",
        usage=SimpleNamespace(input_tokens=42, output_tokens=7),
    )
    monkeypatch.setattr(provider._client.messages, "create", lambda **kwargs: fake_response)

    request = CompletionRequest(
        messages=[Message(role=ChatRole.USER, content="find the add function")],
        tools=[ToolDefinition(name="search_code", description="search", input_schema={})],
    )
    result = provider.complete(request, model="claude-opus-5")

    assert result.stop_reason == StopReason.TOOL_USE
    assert result.message.tool_calls[0].name == "search_code"
    assert result.usage.input_tokens == 42
    assert result.usage.output_tokens == 7
    assert result.provider == "anthropic"


def test_anthropic_provider_translates_tool_result_messages(monkeypatch):
    provider = AnthropicProvider(api_key="fake-key")
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="done")],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        )

    monkeypatch.setattr(provider._client.messages, "create", fake_create)

    messages = [
        Message(role=ChatRole.USER, content="fix it"),
        Message(role=ChatRole.TOOL, name="run_tests", tool_call_id="call_1", content="1 failed"),
    ]
    provider.complete(CompletionRequest(messages=messages), model="claude-opus-5")

    tool_result_block = captured["messages"][-1]["content"][0]
    assert tool_result_block["type"] == "tool_result"
    assert tool_result_block["tool_use_id"] == "call_1"


def test_openai_provider_parses_tool_call_response(monkeypatch):
    provider = OpenAIProvider(api_key="fake-key")

    fake_message = SimpleNamespace(
        content=None,
        tool_calls=[
            SimpleNamespace(
                id="call_1",
                function=SimpleNamespace(name="read_file", arguments='{"path": "a.py"}'),
            )
        ],
    )
    fake_response = SimpleNamespace(
        choices=[SimpleNamespace(message=fake_message, finish_reason="tool_calls")],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
    )
    monkeypatch.setattr(provider._client.chat.completions, "create", lambda **kwargs: fake_response)

    request = CompletionRequest(
        messages=[Message(role=ChatRole.USER, content="read a.py")],
        tools=[ToolDefinition(name="read_file", description="read", input_schema={})],
    )
    result = provider.complete(request, model="gpt-4.1")

    assert result.stop_reason == StopReason.TOOL_USE
    assert result.message.tool_calls[0].arguments == {"path": "a.py"}
    assert result.usage.input_tokens == 10
