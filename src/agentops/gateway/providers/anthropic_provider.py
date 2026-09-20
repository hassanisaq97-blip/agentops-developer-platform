"""Anthropic-provider for LLM Gateway'et.

Oversætter mellem platformens provider-uafhængige schemas og Anthropic
Messages API (anthropic-python SDK v1.x). Al fejlhåndtering normaliseres til
`ProviderError`, så gatewayen ikke behøver kende til SDK-specifikke exceptions.
"""

from __future__ import annotations

import time
from typing import Any, cast

import anthropic

from agentops.gateway.base import LLMProvider
from agentops.gateway.errors import ProviderError
from agentops.gateway.schemas import (
    ChatRole,
    CompletionRequest,
    CompletionResult,
    Message,
    StopReason,
    TokenUsage,
    ToolCall,
)

_STOP_REASON_MAP = {
    "end_turn": StopReason.END_TURN,
    "tool_use": StopReason.TOOL_USE,
    "max_tokens": StopReason.MAX_TOKENS,
    "stop_sequence": StopReason.END_TURN,
}


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str, timeout_seconds: float = 60.0):
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY mangler — kan ikke oprette AnthropicProvider.")
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout_seconds)

    def complete(self, request: CompletionRequest, *, model: str) -> CompletionResult:
        start = time.monotonic()
        try:
            # Bemærk: anthropic-python v1.x's Messages.create() har ikke længere en
            # top-level `temperature`-parameter (verificeret mod den installerede SDK,
            # ikke antaget fra ældre træningsdata) — determinisme styres i stedet af
            # promptdesign og `tool_choice`.
            response = self._client.messages.create(
                model=cast(Any, model),
                max_tokens=request.max_tokens,
                system=request.system or anthropic.omit,
                messages=cast(Any, self._to_anthropic_messages(request.messages)),
                tools=cast(Any, self._to_anthropic_tools(request.tools))
                if request.tools
                else anthropic.omit,
            )
        except anthropic.APIError as exc:
            raise ProviderError(self.name, str(exc)) from exc

        latency_ms = (time.monotonic() - start) * 1000
        message = self._from_anthropic_message(response)
        stop_reason = _STOP_REASON_MAP.get(response.stop_reason or "end_turn", StopReason.END_TURN)

        return CompletionResult(
            message=message,
            stop_reason=stop_reason,
            usage=TokenUsage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            ),
            latency_ms=latency_ms,
            provider=self.name,
            model=model,
        )

    @staticmethod
    def _to_anthropic_tools(tools: list) -> list[dict]:
        return [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in tools
        ]

    @staticmethod
    def _to_anthropic_messages(messages: list[Message]) -> list[dict]:
        anthropic_messages: list[dict] = []
        for m in messages:
            if m.role == ChatRole.SYSTEM:
                continue  # system håndteres separat via `system`-parameteren
            if m.role == ChatRole.TOOL:
                anthropic_messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": m.tool_call_id,
                                "content": m.content or "",
                            }
                        ],
                    }
                )
            elif m.role == ChatRole.ASSISTANT and m.tool_calls:
                if m.raw_provider_blocks is not None:
                    # Genbruger de rå content-blocks fra Anthropics eget svar (inkl.
                    # eventuelle thinking-blocks med deres signatur) frem for at
                    # genopbygge dem — adaptive thinking kræver, at et thinking-block
                    # echoes uændret tilbage for at modellen kan fortsætte ræsonnementet
                    # fra samme punkt, i stedet for at starte forfra hver tur.
                    anthropic_messages.append(
                        {"role": "assistant", "content": m.raw_provider_blocks}
                    )
                    continue
                content: list[dict] = []
                if m.content:
                    content.append({"type": "text", "text": m.content})
                for tc in m.tool_calls:
                    content.append(
                        {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments}
                    )
                anthropic_messages.append({"role": "assistant", "content": content})
            else:
                anthropic_messages.append({"role": m.role.value, "content": m.content or ""})
        return anthropic_messages

    @staticmethod
    def _from_anthropic_message(response) -> Message:
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, arguments=dict(block.input))
                )
        return Message(
            role=ChatRole.ASSISTANT,
            content="\n".join(text_parts) if text_parts else None,
            tool_calls=tool_calls,
            raw_provider_blocks=[block.model_dump(mode="json") for block in response.content],
        )
