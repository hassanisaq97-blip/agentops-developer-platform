"""Coding agent orchestrator: den agentiske løkke.

    OPGAVE → forstå (system prompt via context-strategi) → vælg tool →
    modtag observation → vælg næste handling → ... → foreslå/implementér
    ændring → validér → afsluttende svar

Repositoryet leveres ALDRIG i sin helhed til modellen. Agenten får kun et
system-prompt (afhængigt af `ContextStrategy`) og skal selv hente resten via
MCP tool calls — det er selve pointen med "kontrolleret context acquisition".

Høj-risiko tool calls (jf. `agentops.agent.risk`) executer ikke automatisk:
løkken stopper og returnerer status AWAITING_APPROVAL, og kaldende kode
(FastAPI-laget) er ansvarlig for at persistere tilstanden og kalde
`resume()`, når et menneske har godkendt eller afvist.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from pathlib import Path

from agentops.agent.context import STRATEGIES_WITH_TOOLS, ContextStrategy, build_system_prompt
from agentops.agent.events import AgentEvent, AgentEventType
from agentops.agent.mcp_client import MCPClient, MCPToolError
from agentops.agent.risk import requires_approval as risk_requires_approval
from agentops.agent.risk import risk_level_for
from agentops.agent.schemas import AgentRunResult, PendingApproval, PendingToolCall, TaskStatus
from agentops.agent.skills import Skill, format_skill_for_prompt, select_skill
from agentops.agent.tool_discovery import discover_relevant_tools
from agentops.gateway.gateway import LLMGateway
from agentops.gateway.schemas import (
    ChatRole,
    CompletionRequest,
    Message,
    TaskComplexity,
    TokenUsage,
    ToolDefinition,
)
from agentops.memory.prompting import format_memories_for_prompt
from agentops.memory.schemas import MemoryRecord
from agentops.observability.tracing import SpanType, mlflow
from agentops.security.secrets import redact_mapping
from agentops.settings import Settings

logger = logging.getLogger(__name__)

_MAX_RESULT_CHARS_IN_CONTEXT = 4000

MemoryRetriever = Callable[[str, str], Awaitable[list[MemoryRecord]]]
"""(workspace_key, query_text) -> relevante tidligere erfaringer."""
MemorySaver = Callable[[str, str, AgentRunResult], Awaitable[None]]
"""(workspace_key, task_description, terminal_result) -> None. Kaldes KUN på et
terminalt resultat (COMPLETED/FAILED/MAX_STEPS_REACHED) — aldrig på en pause,
hvor opgaven endnu ikke er færdig."""
OnCheckpoint = Callable[[list[Message], list[AgentEvent], TokenUsage], Awaitable[None]]
"""Kaldes efter hver model-tur under en kørsel, så kaldende kode (API-laget) kan
persistere fremskridt løbende — se ADR-0014 om checkpoints og recovery."""

_TERMINAL_STATUSES = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.MAX_STEPS_REACHED}


class AgentOrchestrator:
    def __init__(
        self,
        gateway: LLMGateway,
        settings: Settings,
        *,
        memory_retriever: MemoryRetriever | None = None,
        memory_saver: MemorySaver | None = None,
    ):
        self._gateway = gateway
        self._settings = settings
        self._memory_retriever = memory_retriever
        self._memory_saver = memory_saver

    async def run(
        self,
        task: str,
        workspace_root: Path,
        *,
        context_strategy: ContextStrategy = ContextStrategy.TARGETED_MCP,
        complexity: TaskComplexity = TaskComplexity.SIMPLE,
        on_checkpoint: OnCheckpoint | None = None,
        max_continuous_steps: int | None = None,
    ) -> AgentRunResult:
        with mlflow.start_span(name="agent_run", span_type=SpanType.AGENT) as span:
            span.set_inputs(
                {
                    "task": task,
                    "context_strategy": context_strategy.value,
                    "complexity": complexity.value,
                }
            )
            result = await self._run(
                task,
                workspace_root,
                context_strategy=context_strategy,
                complexity=complexity,
                on_checkpoint=on_checkpoint,
                max_continuous_steps=max_continuous_steps,
            )
            await self._maybe_save_memory(workspace_root, task, result)
            span.set_outputs(self._span_outputs(result))
            return result

    async def _run(
        self,
        task: str,
        workspace_root: Path,
        *,
        context_strategy: ContextStrategy,
        complexity: TaskComplexity,
        on_checkpoint: OnCheckpoint | None = None,
        max_continuous_steps: int | None = None,
    ) -> AgentRunResult:
        skill = select_skill(task)
        system_prompt = build_system_prompt(context_strategy, workspace_root, task)
        conversation = [Message(role=ChatRole.USER, content=task)]
        events: list[AgentEvent] = []

        if skill is not None:
            system_prompt = f"{system_prompt}\n\n{format_skill_for_prompt(skill)}"
            events.append(
                AgentEvent(
                    step=len(events),
                    type=AgentEventType.SKILL_SELECTED,
                    result_summary=skill.name,
                )
            )

        memories = await self._maybe_retrieve_memory(workspace_root, task)
        if memories:
            system_prompt = f"{system_prompt}\n\n{format_memories_for_prompt(memories)}"
            events.append(
                AgentEvent(
                    step=len(events),
                    type=AgentEventType.MEMORY_RETRIEVED,
                    result_summary=f"{len(memories)} relevante tidligere erfaringer",
                )
            )

        if context_strategy not in STRATEGIES_WITH_TOOLS:
            result = await self._run_without_tools(
                task, system_prompt, conversation, complexity, prefix_events=events
            )
            result.skill_selected = skill.name if skill else None
            result.memory_hits = len(memories)
            return result

        async with MCPClient(str(workspace_root)) as mcp_client:
            all_tools = await mcp_client.list_tool_definitions()
            tools = self._select_tools(task, all_tools, skill)
            if self._settings.agent_dynamic_tool_discovery:
                events.append(
                    AgentEvent(
                        step=len(events),
                        type=AgentEventType.TOOLS_DISCOVERED,
                        result_summary=f"{len(tools)}/{len(all_tools)} tools",
                        arguments={"discovered": [t.name for t in tools]},
                    )
                )
            result = await self._run_loop(
                task=task,
                system_prompt=system_prompt,
                conversation=conversation,
                tools=tools,
                mcp_client=mcp_client,
                complexity=complexity,
                events=events,
                approval_decision=None,
                on_checkpoint=on_checkpoint,
                max_continuous_steps=max_continuous_steps,
            )
            result.skill_selected = skill.name if skill else None
            result.memory_hits = len(memories)
            result.tools_available_count = len(all_tools)
            result.tools_discovered_count = len(tools)
            return result

    async def _maybe_retrieve_memory(self, workspace_root: Path, task: str) -> list[MemoryRecord]:
        if self._memory_retriever is None:
            return []
        from agentops.memory.schemas import workspace_key_for

        workspace_key = workspace_key_for(str(workspace_root))
        return await self._memory_retriever(workspace_key, task)

    async def _maybe_save_memory(
        self, workspace_root: Path, task: str, result: AgentRunResult
    ) -> None:
        if self._memory_saver is None or result.status not in _TERMINAL_STATUSES:
            return
        from agentops.memory.schemas import workspace_key_for

        workspace_key = workspace_key_for(str(workspace_root))
        await self._memory_saver(workspace_key, task, result)

    def _select_tools(
        self, task: str, all_tools: list[ToolDefinition], skill: Skill | None
    ) -> list[ToolDefinition]:
        if not self._settings.agent_dynamic_tool_discovery:
            return all_tools
        return discover_relevant_tools(task, all_tools, skill)

    @staticmethod
    def _span_outputs(result: AgentRunResult) -> dict:
        return {
            "status": result.status.value,
            "tools_used": result.tools_used,
            "tests_run": result.tests_run,
            "tests_passed": result.tests_passed,
            "tests_failed": result.tests_failed,
            "files_changed": result.files_changed,
            "input_tokens": result.total_usage.input_tokens,
            "output_tokens": result.total_usage.output_tokens,
            "provider": result.provider,
            "model": result.model,
        }

    async def resume(
        self,
        task: str,
        workspace_root: Path,
        conversation_state: list[Message],
        pending_approval: PendingApproval,
        *,
        approved: bool,
        context_strategy: ContextStrategy = ContextStrategy.TARGETED_MCP,
        complexity: TaskComplexity = TaskComplexity.SIMPLE,
        prior_events: list[AgentEvent] | None = None,
        on_checkpoint: OnCheckpoint | None = None,
        max_continuous_steps: int | None = None,
        memory_hits: int = 0,
    ) -> AgentRunResult:
        """`memory_hits` skal være den værdi, den OPRINDELIGE `run()`-kald returnerede
        (`AgentRunResult.memory_hits`) — memory hentes bevidst kun ved opgavens
        allerførste trin (se ADR-0013), så `resume()` genhenter den ikke, men skal
        stadig rapportere den korrekt videre i stedet for at nulstille den til 0."""
        with mlflow.start_span(name="agent_resume", span_type=SpanType.AGENT) as span:
            span.set_inputs(
                {
                    "task": task,
                    "tool_names": [tc.tool_name for tc in pending_approval.tool_calls],
                    "approved": approved,
                }
            )
            result = await self._resume(
                task,
                workspace_root,
                conversation_state,
                pending_approval,
                approved=approved,
                context_strategy=context_strategy,
                complexity=complexity,
                prior_events=prior_events,
                on_checkpoint=on_checkpoint,
                max_continuous_steps=max_continuous_steps,
            )
            result.memory_hits = memory_hits
            await self._maybe_save_memory(workspace_root, task, result)
            span.set_outputs(self._span_outputs(result))
            return result

    async def _resume(
        self,
        task: str,
        workspace_root: Path,
        conversation_state: list[Message],
        pending_approval: PendingApproval,
        *,
        approved: bool,
        context_strategy: ContextStrategy = ContextStrategy.TARGETED_MCP,
        complexity: TaskComplexity = TaskComplexity.SIMPLE,
        prior_events: list[AgentEvent] | None = None,
        on_checkpoint: OnCheckpoint | None = None,
        max_continuous_steps: int | None = None,
    ) -> AgentRunResult:
        skill = select_skill(task)
        system_prompt = build_system_prompt(context_strategy, workspace_root, task)
        if skill is not None:
            system_prompt = f"{system_prompt}\n\n{format_skill_for_prompt(skill)}"
        async with MCPClient(str(workspace_root)) as mcp_client:
            all_tools = await mcp_client.list_tool_definitions()
            tools = self._select_tools(task, all_tools, skill)
            events = list(prior_events or [])
            conversation = list(conversation_state)

            # Alle tool calls fra samme model-tur godkendes/afvises som én batch (se
            # PendingApproval's docstring) — Anthropic/OpenAI kræver et tool_result for
            # HVERT tool_use i den forudgående assistant-besked, før samtalen kan
            # fortsætte, så vi kan ikke eksekvere nogle og lade andre afvente.
            if approved:
                for pending_call in pending_approval.tool_calls:
                    events.append(
                        AgentEvent(
                            step=len(events),
                            type=AgentEventType.APPROVAL_GRANTED,
                            tool_name=pending_call.tool_name,
                            tool_call_id=pending_call.id,
                        )
                    )
                    observation = await self._execute_tool(
                        mcp_client,
                        pending_call.tool_name,
                        pending_call.arguments,
                        pending_call.id,
                        len(events),
                        events,
                    )
                    conversation.append(observation)
            else:
                for pending_call in pending_approval.tool_calls:
                    events.append(
                        AgentEvent(
                            step=len(events),
                            type=AgentEventType.APPROVAL_DENIED,
                            tool_name=pending_call.tool_name,
                            tool_call_id=pending_call.id,
                        )
                    )
                    conversation.append(
                        Message(
                            role=ChatRole.TOOL,
                            name=pending_call.tool_name,
                            tool_call_id=pending_call.id,
                            content='{"denied_by_human": true}',
                        )
                    )

            result = await self._run_loop(
                task=task,
                system_prompt=system_prompt,
                conversation=conversation,
                tools=tools,
                mcp_client=mcp_client,
                complexity=complexity,
                events=events,
                approval_decision=approved,
                on_checkpoint=on_checkpoint,
                max_continuous_steps=max_continuous_steps,
            )
            result.skill_selected = skill.name if skill else None
            result.tools_available_count = len(all_tools)
            result.tools_discovered_count = len(tools)
            return result

    async def continue_task(
        self,
        task: str,
        workspace_root: Path,
        conversation_state: list[Message],
        *,
        context_strategy: ContextStrategy = ContextStrategy.TARGETED_MCP,
        complexity: TaskComplexity = TaskComplexity.SIMPLE,
        prior_events: list[AgentEvent] | None = None,
        on_checkpoint: OnCheckpoint | None = None,
        max_continuous_steps: int | None = None,
        memory_hits: int = 0,
    ) -> AgentRunResult:
        """Genoptager en PAUSED opgave (checkpoint-baseret) — IKKE en godkendelses-
        beslutning, se `resume()` for det. Bruges til langvarige opgaver, der
        bevidst er delt op i flere afgrænsede kørsler, og til recovery efter en
        uventet API-nedlukning (se ADR-0014). Memory hentes IKKE igen her — det
        sker kun ved opgavens allerførste `run()`-kald; `memory_hits` skal derfor
        være værdien fra det oprindelige `run()`-kald, så den rapporteres korrekt
        videre i stedet for at blive nulstillet til 0."""
        with mlflow.start_span(name="agent_continue", span_type=SpanType.AGENT) as span:
            span.set_inputs({"task": task})
            skill = select_skill(task)
            system_prompt = build_system_prompt(context_strategy, workspace_root, task)
            if skill is not None:
                system_prompt = f"{system_prompt}\n\n{format_skill_for_prompt(skill)}"

            async with MCPClient(str(workspace_root)) as mcp_client:
                all_tools = await mcp_client.list_tool_definitions()
                tools = self._select_tools(task, all_tools, skill)
                result = await self._run_loop(
                    task=task,
                    system_prompt=system_prompt,
                    conversation=list(conversation_state),
                    tools=tools,
                    mcp_client=mcp_client,
                    complexity=complexity,
                    events=list(prior_events or []),
                    approval_decision=None,
                    on_checkpoint=on_checkpoint,
                    max_continuous_steps=max_continuous_steps,
                )
                result.skill_selected = skill.name if skill else None
                result.tools_available_count = len(all_tools)
                result.tools_discovered_count = len(tools)
                result.memory_hits = memory_hits
            await self._maybe_save_memory(workspace_root, task, result)
            span.set_outputs(self._span_outputs(result))
            return result

    async def _run_without_tools(
        self,
        task: str,
        system_prompt: str,
        conversation: list[Message],
        complexity: TaskComplexity,
        prefix_events: list[AgentEvent] | None = None,
    ) -> AgentRunResult:
        request = CompletionRequest(
            messages=conversation, system=system_prompt, complexity=complexity
        )
        result = self._gateway.complete(request)
        events = [
            *(prefix_events or []),
            AgentEvent(
                step=len(prefix_events or []),
                type=AgentEventType.TASK_STARTED,
                rationale="Ingen tools tilgængelige i denne context-strategi.",
            ),
            AgentEvent(
                step=len(prefix_events or []) + 1,
                type=AgentEventType.FINAL_ANSWER,
                result_summary=result.message.content,
            ),
        ]
        return AgentRunResult(
            status=TaskStatus.COMPLETED,
            task_summary=task,
            final_answer=result.message.content,
            events=events,
            conversation_state=[*conversation, result.message],
            total_usage=result.usage,
            total_latency_ms=result.latency_ms,
            provider=result.provider,
            model=result.model,
            used_fallback=result.used_fallback,
            warnings=[
                "Denne context-strategi har ingen tools — svaret er ikke baseret på det faktiske repository."
            ],
        )

    async def _run_loop(
        self,
        *,
        task: str,
        system_prompt: str,
        conversation: list[Message],
        tools: list[ToolDefinition],
        mcp_client: MCPClient,
        complexity: TaskComplexity,
        events: list[AgentEvent],
        approval_decision: bool | None,
        on_checkpoint: OnCheckpoint | None = None,
        max_continuous_steps: int | None = None,
    ) -> AgentRunResult:
        max_steps = self._settings.agent_max_tool_calls
        total_usage = TokenUsage()
        total_latency_ms = 0.0
        provider: str | None = None
        model: str | None = None
        used_fallback = False
        step = len(events)
        steps_this_call = 0

        if not any(e.type == AgentEventType.TASK_STARTED for e in events):
            events.append(
                AgentEvent(step=step, type=AgentEventType.TASK_STARTED, result_summary=task)
            )
            step += 1

        while step < max_steps:
            if max_continuous_steps is not None and steps_this_call >= max_continuous_steps:
                events.append(
                    AgentEvent(
                        step=step,
                        type=AgentEventType.TASK_PAUSED,
                        result_summary=(
                            f"Pause efter {steps_this_call} trin i denne kørsel — "
                            "genoptages via continue_task()."
                        ),
                    )
                )
                return self._finalize(
                    TaskStatus.PAUSED,
                    task,
                    None,
                    conversation,
                    events,
                    total_usage,
                    total_latency_ms,
                    provider,
                    model,
                    used_fallback,
                    None,
                )

            request = CompletionRequest(
                messages=conversation, tools=tools, system=system_prompt, complexity=complexity
            )
            result = self._gateway.complete(request)
            total_usage = TokenUsage(
                input_tokens=total_usage.input_tokens + result.usage.input_tokens,
                output_tokens=total_usage.output_tokens + result.usage.output_tokens,
            )
            total_latency_ms += result.latency_ms
            provider, model, used_fallback = (
                result.provider,
                result.model,
                used_fallback or result.used_fallback,
            )
            conversation.append(result.message)
            steps_this_call += 1

            if not result.message.tool_calls:
                events.append(
                    AgentEvent(
                        step=step,
                        type=AgentEventType.FINAL_ANSWER,
                        result_summary=result.message.content,
                    )
                )
                return self._finalize(
                    TaskStatus.COMPLETED,
                    task,
                    result.message.content,
                    conversation,
                    events,
                    total_usage,
                    total_latency_ms,
                    provider,
                    model,
                    used_fallback,
                    None,
                )

            # Claude/OpenAI kan returnere flere parallelle tool_use-blocks i ét svar.
            # Vi behandler dem alle her — se docs/adr/0011 for hvorfor godkendelse
            # sker som én batch-beslutning for hele turen frem for pr. tool call.
            tool_calls = result.message.tool_calls
            pending_calls: list[PendingToolCall] = []
            for i, tool_call in enumerate(tool_calls):
                risk = risk_level_for(tool_call.name)
                events.append(
                    AgentEvent(
                        step=step,
                        type=AgentEventType.TOOL_CALL,
                        tool_name=tool_call.name,
                        tool_call_id=tool_call.id,
                        arguments=redact_mapping(tool_call.arguments),
                        risk_level=risk,
                        rationale=result.message.content if i == 0 else None,
                    )
                )
                step += 1
                pending_calls.append(
                    PendingToolCall(
                        id=tool_call.id,
                        tool_name=tool_call.name,
                        arguments=tool_call.arguments,
                        risk_level=risk,
                    )
                )

            batch_needs_approval = any(
                risk_requires_approval(
                    pc.tool_name, auto_approve_high_risk=self._settings.agent_auto_approve_high_risk
                )
                for pc in pending_calls
            )

            if batch_needs_approval:
                for pc in pending_calls:
                    if risk_requires_approval(
                        pc.tool_name,
                        auto_approve_high_risk=self._settings.agent_auto_approve_high_risk,
                    ):
                        events.append(
                            AgentEvent(
                                step=step,
                                type=AgentEventType.APPROVAL_REQUIRED,
                                tool_name=pc.tool_name,
                                tool_call_id=pc.id,
                                risk_level=pc.risk_level,
                            )
                        )
                        step += 1
                return self._finalize(
                    TaskStatus.AWAITING_APPROVAL,
                    task,
                    None,
                    conversation,
                    events,
                    total_usage,
                    total_latency_ms,
                    provider,
                    model,
                    used_fallback,
                    PendingApproval(tool_calls=pending_calls),
                )

            for tool_call in tool_calls:
                observation = await self._execute_tool(
                    mcp_client, tool_call.name, tool_call.arguments, tool_call.id, step, events
                )
                conversation.append(observation)
                step += 1

            if on_checkpoint is not None:
                await on_checkpoint(conversation, events, total_usage)

        events.append(AgentEvent(step=step, type=AgentEventType.MAX_STEPS_REACHED))
        return self._finalize(
            TaskStatus.MAX_STEPS_REACHED,
            task,
            None,
            conversation,
            events,
            total_usage,
            total_latency_ms,
            provider,
            model,
            used_fallback,
            None,
        )

    async def _execute_tool(
        self,
        mcp_client: MCPClient,
        name: str,
        arguments: dict,
        tool_call_id: str,
        step: int,
        events: list[AgentEvent],
    ) -> Message:
        try:
            content = await mcp_client.call_tool(name, arguments)
            events.append(
                AgentEvent(
                    step=step,
                    type=AgentEventType.TOOL_RESULT,
                    tool_name=name,
                    tool_call_id=tool_call_id,
                    result_summary=content[:_MAX_RESULT_CHARS_IN_CONTEXT],
                )
            )
            return Message(
                role=ChatRole.TOOL,
                name=name,
                tool_call_id=tool_call_id,
                content=content[:_MAX_RESULT_CHARS_IN_CONTEXT],
            )
        except MCPToolError as exc:
            events.append(
                AgentEvent(
                    step=step,
                    type=AgentEventType.TOOL_ERROR,
                    tool_name=name,
                    tool_call_id=tool_call_id,
                    result_summary=str(exc),
                )
            )
            return Message(
                role=ChatRole.TOOL,
                name=name,
                tool_call_id=tool_call_id,
                content=f'{{"error": {str(exc)!r}}}',
            )

    def _finalize(
        self,
        status: TaskStatus,
        task: str,
        final_answer: str | None,
        conversation: list[Message],
        events: list[AgentEvent],
        total_usage: TokenUsage,
        total_latency_ms: float,
        provider: str | None,
        model: str | None,
        used_fallback: bool,
        pending_approval: PendingApproval | None,
    ) -> AgentRunResult:
        tool_calls_by_id = {
            e.tool_call_id: e
            for e in events
            if e.type == AgentEventType.TOOL_CALL and e.tool_call_id
        }
        tools_used = [
            e.tool_name for e in events if e.type == AgentEventType.TOOL_CALL and e.tool_name
        ]
        files_examined = sorted(
            {
                e.arguments["path"]
                for e in events
                if e.type == AgentEventType.TOOL_CALL
                and e.tool_name == "read_file"
                and e.arguments
                and "path" in e.arguments
            }
        )
        changed_paths: set[str] = set()
        for result_event in events:
            if (
                result_event.type != AgentEventType.TOOL_RESULT
                or result_event.tool_name not in {"edit_file", "apply_patch"}
                or not result_event.result_summary
                or '"error"' in result_event.result_summary
                or result_event.tool_call_id is None
            ):
                continue
            call_event = tool_calls_by_id.get(result_event.tool_call_id)
            if call_event is None or not call_event.arguments:
                continue
            path = call_event.arguments.get("path") or self._extract_patch_path(
                call_event.arguments
            )
            if path:
                changed_paths.add(path)
        files_changed = sorted(changed_paths)
        run_tests_results = [
            e.result_summary
            for e in events
            if e.type == AgentEventType.TOOL_RESULT and e.tool_name == "run_tests"
        ]
        tests_passed, tests_failed = (
            self._parse_last_test_result(run_tests_results[-1])
            if run_tests_results
            else (None, None)
        )

        warnings: list[str] = []
        if status == TaskStatus.MAX_STEPS_REACHED:
            warnings.append("Maksimalt antal tool calls nået, før opgaven blev afsluttet.")
        if any(e.type == AgentEventType.TOOL_ERROR for e in events):
            warnings.append("Mindst ét tool call fejlede under kørslen.")

        return AgentRunResult(
            status=status,
            task_summary=task,
            final_answer=final_answer,
            tools_used=tools_used,
            files_examined=files_examined,
            files_changed=files_changed,
            tests_run="run_tests" in tools_used,
            tests_passed=tests_passed,
            tests_failed=tests_failed,
            warnings=warnings,
            events=events,
            conversation_state=conversation,
            pending_approval=pending_approval,
            total_tool_calls=len(tools_used),
            total_usage=total_usage,
            total_latency_ms=total_latency_ms,
            provider=provider,
            model=model,
            used_fallback=used_fallback,
        )

    @staticmethod
    def _extract_patch_path(arguments: dict | None) -> str | None:
        if not arguments:
            return None
        diff_text = arguments.get("diff_text", "")
        for line in diff_text.splitlines():
            if line.startswith("+++ b/"):
                return line.removeprefix("+++ b/")
        return None

    @staticmethod
    def _parse_last_test_result(content: str | None) -> tuple[int | None, int | None]:
        if not content:
            return None, None
        passed_match = re.search(r'"passed":\s*(\d+)', content)
        failed_match = re.search(r'"failed":\s*(\d+)', content)
        passed = int(passed_match.group(1)) if passed_match else None
        failed = int(failed_match.group(1)) if failed_match else None
        return passed, failed
