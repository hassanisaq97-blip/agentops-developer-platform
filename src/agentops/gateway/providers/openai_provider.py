"""OpenAI-provider for LLM Gateway'et.

Bruger Chat Completions API (openai-python SDK), som fortsat understøttes ved
siden af den nyere Responses API og har et stabilt tool-calling-format, der
passer godt til vores provider-uafhængige schema.
"""

from __future__ import annotations

import json
import time
from typing import Any, cast

import openai

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
    "stop": StopReason.END_TURN,
    "tool_calls": StopReason.TOOL_USE,
    "length": StopReason.MAX_TOKENS,
}


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str, timeout_seconds: float = 60.0):
        if not api_key:
            raise ValueError("OPENAI_API_KEY mangler — kan ikke oprette OpenAIProvider.")
        self._client = openai.OpenAI(api_key=api_key, timeout=timeout_seconds)

    def complete(self, request: CompletionRequest, *, model: str) -> CompletionResult:
        start = time.monotonic()
        messages = self._to_openai_messages(request)
        try:
            response = self._client.chat.completions.create(
                model=model,
                messages=cast(Any, messages),
                max_tokens=request.max_tokens,
                temperature=request.temperature,
                tools=cast(Any, self._to_openai_tools(request.tools))
                if request.tools
                else openai.omit,
            )
        except openai.APIError as exc:
            raise ProviderError(self.name, str(exc)) from exc

        latency_ms = (time.monotonic() - start) * 1000
        choice = response.choices[0]
        message = self._from_openai_message(choice.message)
        stop_reason = _STOP_REASON_MAP.get(choice.finish_reason, StopReason.END_TURN)

        usage = response.usage
        return CompletionResult(
            message=message,
            stop_reason=stop_reason,
            usage=TokenUsage(
                input_tokens=usage.prompt_tokens if usage else 0,
                output_tokens=usage.completion_tokens if usage else 0,
            ),
            latency_ms=latency_ms,
            provider=self.name,
            model=model,
        )

    @staticmethod
    def _to_openai_tools(tools: list) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in tools
        ]

    @staticmethod
    def _to_openai_messages(request: CompletionRequest) -> list[dict]:
        messages: list[dict] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        for m in request.messages:
            if m.role == ChatRole.SYSTEM:
                messages.append({"role": "system", "content": m.content or ""})
            elif m.role == ChatRole.TOOL:
                messages.append(
                    {"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content or ""}
                )
            elif m.role == ChatRole.ASSISTANT and m.tool_calls:
                messages.append(
                    {
                        "role": "assistant",
                        "content": m.content,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": json.dumps(tc.arguments),
                                },
                            }
                            for tc in m.tool_calls
                        ],
                    }
                )
            else:
                messages.append({"role": m.role.value, "content": m.content or ""})
        return messages

    @staticmethod
    def _from_openai_message(message) -> Message:
        tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                try:
                    arguments = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    arguments = {}
                tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=arguments))
        return Message(role=ChatRole.ASSISTANT, content=message.content, tool_calls=tool_calls)
