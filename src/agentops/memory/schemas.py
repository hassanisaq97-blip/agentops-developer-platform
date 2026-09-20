"""Schemas for agent-memory: strukturerede erfaringer, ikke rå samtaler.

En `MemoryRecord` er ALDRIG en kopi af en hel samtale — kun et lille, udtrukket
resumé (se `agentops.memory.extraction`), sanitiseret (se `agentops.memory.sanitize`)
før det gemmes.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


def workspace_key_for(workspace_root: str) -> str:
    """Stabil, kort nøgle for et workspace — undgår at gemme rå, miljøspecifikke
    filstier (fx forskellige tmp-mapper pr. eval-kørsel for samme fixture) direkte
    i memory-rækker, og holder nøglen fri af SQLAlchemy/DB-afhængigheder, så
    `AgentOrchestrator` kan bruge den uden at importere persistence-laget."""
    return hashlib.sha256(workspace_root.encode("utf-8")).hexdigest()[:16]


class MemoryCategory(StrEnum):
    TASK_OUTCOME = "task_outcome"
    """Kort resumé af en tidligere opgave og dens udfald."""
    TOOL_EFFECTIVENESS = "tool_effectiveness"
    """Hvilke tools blev brugt til at løse en given type opgave."""
    LESSON_LEARNED = "lesson_learned"
    """En advarsel, en ændret fil, eller anden konkret erfaring fra en kørsel."""


class MemoryRecord(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    workspace_key: str
    """Identificerer HVILKET repository erfaringen stammer fra — memory blandes
    aldrig på tværs af workspaces, medmindre man eksplicit søger globalt."""
    category: MemoryCategory
    summary: str
    """Saniteret, længde-begrænset tekst — se agentops.memory.sanitize."""
    tags: list[str] = Field(default_factory=list)
    outcome: str = "unknown"
    """'success' | 'failure' | 'unknown' — bruges til at vægte relevans."""
    flagged: bool = False
    """True hvis sanitizeren fandt et muligt prompt injection-forsøg i kildeteksten.
    Flagged memory bliver ALDRIG returneret af `MemoryStore.search` — se ADR-0013."""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
