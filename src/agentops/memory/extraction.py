"""Udtrækker et LILLE antal strukturerede erfaringer fra en agent-kørsel.

Bevidst IKKE en kopi af samtalen: kun de allerede-strukturerede felter på
`AgentRunResult` (tools_used, files_changed, warnings, final_answer,
tests_passed/failed) bliver til memory — aldrig rå `conversation_state`
eller rå tool-result-tekst, som kan indeholde uverificeret fil-indhold.
"""

from __future__ import annotations

import re

from agentops.agent.schemas import AgentRunResult, TaskStatus
from agentops.memory.sanitize import sanitize_memory_text
from agentops.memory.schemas import MemoryCategory, MemoryRecord

_KEYWORD_PATTERN = re.compile(r"[a-zA-ZæøåÆØÅ0-9_./-]{4,}")


def extract_memories(
    *, workspace_key: str, task_description: str, result: AgentRunResult
) -> list[MemoryRecord]:
    """Bygger op til tre memory-kandidater ud fra én afsluttet agent-kørsel."""
    keywords = _keywords(task_description)
    outcome = _outcome(result)
    records: list[MemoryRecord] = []

    task_text, task_flagged = sanitize_memory_text(
        f"Opgave: {task_description.strip()} | Status: {result.status.value} | "
        f"Svar: {result.final_answer or '(intet afsluttende svar)'}"
    )
    records.append(
        MemoryRecord(
            workspace_key=workspace_key,
            category=MemoryCategory.TASK_OUTCOME,
            summary=task_text,
            tags=keywords,
            outcome=outcome,
            flagged=task_flagged,
        )
    )

    if result.tools_used:
        tools_text, tools_flagged = sanitize_memory_text(
            "Værktøjer der løste opgaven: " + ", ".join(sorted(set(result.tools_used)))
        )
        records.append(
            MemoryRecord(
                workspace_key=workspace_key,
                category=MemoryCategory.TOOL_EFFECTIVENESS,
                summary=tools_text,
                tags=[*keywords, *sorted(set(result.tools_used))],
                outcome=outcome,
                flagged=tools_flagged,
            )
        )

    lesson_parts = []
    if result.files_changed:
        lesson_parts.append("Filer ændret: " + ", ".join(result.files_changed))
    if result.tests_run:
        lesson_parts.append(f"Tests: {result.tests_passed} bestået, {result.tests_failed} fejlet")
    for warning in result.warnings:
        lesson_parts.append(f"Advarsel: {warning}")

    if lesson_parts:
        lesson_text, lesson_flagged = sanitize_memory_text(" | ".join(lesson_parts))
        records.append(
            MemoryRecord(
                workspace_key=workspace_key,
                category=MemoryCategory.LESSON_LEARNED,
                summary=lesson_text,
                tags=[*keywords, *result.files_changed],
                outcome=outcome,
                flagged=lesson_flagged,
            )
        )

    return records


def _outcome(result: AgentRunResult) -> str:
    if result.status == TaskStatus.COMPLETED and (result.tests_failed or 0) == 0:
        return "success"
    if result.status in (TaskStatus.FAILED, TaskStatus.MAX_STEPS_REACHED):
        return "failure"
    return "unknown"


def _keywords(text: str, *, max_keywords: int = 12) -> list[str]:
    words = {w.lower() for w in _KEYWORD_PATTERN.findall(text)}
    return sorted(words)[:max_keywords]
