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


class _FakeBlock(SimpleNamespace):
    """Mimics an Anthropic SDK content block closely enough for our translation
    code: attribute access (`block.type`) plus `.model_dump()`, since real
    blocks are pydantic models and `_from_anthropic_message` calls that."""

    def model_dump(self, **_kwargs):
        return dict(self.__dict__)


def test_anthropic_provider_parses_tool_use_response(monkeypatch):
    provider = AnthropicProvider(api_key="fake-key")

    fake_response = SimpleNamespace(
        content=[
            _FakeBlock(type="tool_use", id="call_1", name="search_code", input={"query": "def add"})
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
            content=[_FakeBlock(type="text", text="done")],
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


def test_anthropic_provider_replays_raw_blocks_for_thinking_continuity(monkeypatch):
    """Claude Opus 5/Sonnet 5 run adaptive thinking by default; a thinking block must be
    echoed back unchanged (with its signature) for the model to continue reasoning from
    the same point, instead of restarting on the next turn — see docs/adr/0002."""
    provider = AnthropicProvider(api_key="fake-key")

    first_response = SimpleNamespace(
        content=[
            _FakeBlock(type="thinking", thinking="", signature="sig-abc"),
            _FakeBlock(type="tool_use", id="call_1", name="run_tests", input={}),
        ],
        stop_reason="tool_use",
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            content=[_FakeBlock(type="text", text="done")],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        )

    monkeypatch.setattr(provider._client.messages, "create", fake_create)

    request = CompletionRequest(messages=[Message(role=ChatRole.USER, content="fix it")])
    assistant_message = provider._from_anthropic_message(first_response)
    assert assistant_message.raw_provider_blocks[0]["type"] == "thinking"
    assert assistant_message.raw_provider_blocks[0]["signature"] == "sig-abc"

    request.messages.append(assistant_message)
    request.messages.append(
        Message(role=ChatRole.TOOL, name="run_tests", tool_call_id="call_1", content="ok")
    )
    provider.complete(request, model="claude-opus-5")

    replayed_assistant_message = next(m for m in captured["messages"] if m["role"] == "assistant")
    assert replayed_assistant_message["content"] == assistant_message.raw_provider_blocks


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
