"""Deterministic test provider.

Formål: gøre HELE platformen (agent, evals, CI) testbar uden API-nøgler og
uden netværkskald til en rigtig LLM. Dette er IKKE en agent-hjerne — det er en
lille, gennemsigtig state machine, der genkender én bestemt opgavetype
("find og ret en fejlende test i et lille Python-modul") og reagerer
deterministisk på tool-resultater fra tidligere trin i samtalen.

Al output fra denne provider er mærket med `provider="test"` og
`model="deterministic-v1"` overalt i traces og evalueringsresultater, så det
aldrig kan forveksles med et rigtigt LLM-svar. Token-usage er et estimat
baseret på tegnlængde og skal ALDRIG citeres som et mål for en rigtig models
faktiske forbrug — det bruges udelukkende til at holde gateway-interfacet
ensartet på tværs af providers.
"""

from __future__ import annotations

import json
import re
import time
import uuid

from agentops.gateway.base import LLMProvider
from agentops.gateway.schemas import (
    ChatRole,
    CompletionRequest,
    CompletionResult,
    Message,
    StopReason,
    TokenUsage,
    ToolCall,
)

MODEL_ID = "deterministic-v1"

_FAILED_JSON_PATTERN = re.compile(r'"failed":\s*(\d+)')
_PATH_JSON_PATTERN = re.compile(r'"path":\s*"([^"]+)"')
_FAILED_TEST_NAME_PATTERN = re.compile(r"FAILED\s+\S+::test_(\w+)")


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class DeterministicTestProvider(LLMProvider):
    name = "test"

    def complete(self, request: CompletionRequest, *, model: str) -> CompletionResult:
        start = time.monotonic()
        called_tools = self._called_tool_sequence(request.messages)
        message = self._next_step(request, called_tools)
        latency_ms = (time.monotonic() - start) * 1000

        prompt_text = "".join(m.content or "" for m in request.messages)
        usage = TokenUsage(
            input_tokens=_estimate_tokens(prompt_text),
            output_tokens=_estimate_tokens(
                message.content or json.dumps([tc.model_dump() for tc in message.tool_calls])
            ),
        )
        stop_reason = StopReason.TOOL_USE if message.tool_calls else StopReason.END_TURN
        return CompletionResult(
            message=message,
            stop_reason=stop_reason,
            usage=usage,
            latency_ms=latency_ms,
            provider=self.name,
            model=MODEL_ID,
        )

    @staticmethod
    def _called_tool_sequence(messages: list[Message]) -> list[str]:
        return [tc.name for m in messages for tc in m.tool_calls]

    def _last_tool_result_content(self, messages: list[Message], tool_name: str) -> str | None:
        for m in reversed(messages):
            if m.role == ChatRole.TOOL and m.name == tool_name:
                return m.content
        return None

    def _next_step(self, request: CompletionRequest, called_tools: list[str]) -> Message:
        available = {t.name for t in request.tools}

        def tool_message(name: str, arguments: dict) -> Message:
            return Message(
                role=ChatRole.ASSISTANT,
                content=None,
                tool_calls=[
                    ToolCall(id=f"call_{uuid.uuid4().hex[:8]}", name=name, arguments=arguments)
                ],
            )

        def final(text: str) -> Message:
            return Message(role=ChatRole.ASSISTANT, content=text)

        # Trin 1: orientér dig i repositoryet.
        if "get_repository_status" in available and "get_repository_status" not in called_tools:
            return tool_message("get_repository_status", {})

        # Trin 2: kør test-suiten for at se fejlen.
        run_count = called_tools.count("run_tests")
        if "run_tests" in available and run_count == 0:
            return tool_message("run_tests", {})

        first_run_result = (
            self._last_tool_result_content(request.messages, "run_tests")
            if run_count >= 1
            else None
        )

        # Trin 3: hvis tests fejler, søg efter den relevante funktion.
        if (
            run_count == 1
            and first_run_result
            and self._has_failures(first_run_result)
            and "search_code" in available
            and "search_code" not in called_tools
        ):
            function_name = self._extract_failing_function(first_run_result, request.messages)
            return tool_message("search_code", {"query": f"def {function_name}"})

        # Trin 4: læs filen, som søgningen fandt.
        if (
            "search_code" in called_tools
            and "read_file" in available
            and "read_file" not in called_tools
        ):
            search_result = self._last_tool_result_content(request.messages, "search_code")
            path = self._extract_first_path(search_result) if search_result else None
            if path:
                return tool_message("read_file", {"path": path})

        # Trin 5: forsøg at generere og anvende en rettelse.
        if (
            "read_file" in called_tools
            and "apply_patch" in available
            and "apply_patch" not in called_tools
        ):
            file_content = self._last_tool_result_content(request.messages, "read_file")
            search_result = self._last_tool_result_content(request.messages, "search_code")
            path = self._extract_first_path(search_result) if search_result else None
            if file_content and path:
                patch = self._build_minus_to_plus_patch(path, file_content)
                if patch:
                    return tool_message("apply_patch", {"diff_text": patch})
            return final(
                "Kunne ikke automatisk generere en sikker rettelse ud fra det kendte mønster. "
                "Denne deterministiske test-provider genkender kun ét bug-mønster og bør erstattes "
                "af en rigtig LLM-provider for generel problemløsning."
            )

        # Trin 6: valider rettelsen ved at køre tests igen.
        if "apply_patch" in called_tools and run_count == 1 and "run_tests" in available:
            return tool_message("run_tests", {})

        # Trin 7: afsluttende svar.
        second_run_result = (
            self._last_tool_result_content(request.messages, "run_tests")
            if run_count == 2
            else None
        )
        if second_run_result is not None:
            if self._has_failures(second_run_result):
                return final(
                    "Rettelsen blev anvendt, men testsuiten fejler stadig. Yderligere undersøgelse er nødvendig."
                )
            return final("Fejlen blev identificeret og rettet. Alle tests består nu.")

        if run_count >= 1 and first_run_result and not self._has_failures(first_run_result):
            return final("Testsuiten består allerede — ingen fejl fundet.")

        return final("Opgaven kunne ikke gennemføres med de tilgængelige tools.")

    @staticmethod
    def _has_failures(tool_result_content: str) -> bool:
        match = _FAILED_JSON_PATTERN.search(tool_result_content)
        if match is None:
            return False
        return int(match.group(1)) > 0

    @staticmethod
    def _extract_failing_function(run_tests_result: str, messages: list[Message]) -> str:
        combined = run_tests_result + "".join(m.content or "" for m in messages)
        match = _FAILED_TEST_NAME_PATTERN.search(combined)
        return match.group(1) if match else "unknown"

    @staticmethod
    def _extract_first_path(search_result_content: str | None) -> str | None:
        if not search_result_content:
            return None
        match = _PATH_JSON_PATTERN.search(search_result_content)
        return match.group(1) if match else None

    @staticmethod
    def _build_minus_to_plus_patch(path: str, file_content_json: str) -> str | None:
        """Genkender mønstret 'return X - Y' i den nyeste linje-fund og foreslår '+'.

        Dette er bevidst naivt: det er en demonstration af, at deterministiske
        providers kan producere strukturerede tool calls, ikke et forsøg på at
        efterligne generel kodeforståelse.
        """
        try:
            content = json.loads(file_content_json)
        except (json.JSONDecodeError, TypeError):
            content = file_content_json

        if not isinstance(content, str):
            return None

        lines = content.splitlines()
        for i, line in enumerate(lines):
            match = re.match(r"^(\s*)return (\w+) - (\w+)\s*$", line)
            if match:
                indent, left, right = match.groups()
                new_line = f"{indent}return {left} + {right}"
                has_context = i > 0
                old_start = i if has_context else i + 1
                hunk_body = f" {lines[i - 1]}\n" if has_context else ""
                hunk_body += f"-{line}\n+{new_line}\n"
                return f"--- a/{path}\n+++ b/{path}\n@@ -{old_start} +{old_start} @@\n{hunk_body}"
        return None
