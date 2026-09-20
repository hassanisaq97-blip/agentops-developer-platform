"""Persistent memory-lager (PostgreSQL/SQLite via SQLAlchemy).

Bevidst funktioner, der tager en `Session` som parameter — samme mønster som
`agentops.persistence.task_repository` — i stedet for en stateful klasse, der
selv ejer en session. Det holder `AgentOrchestrator` fri af SQLAlchemy: den
kalder kun de plain callables, API-laget forbinder til disse funktioner (se
`agentops.memory.integration`).
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from agentops.memory.schemas import MemoryCategory, MemoryRecord
from agentops.persistence.models import AgentMemoryModel

_TOKEN_PATTERN = re.compile(r"[a-zA-ZæøåÆØÅ0-9_./-]{3,}")


def save(session: Session, records: list[MemoryRecord]) -> None:
    for record in records:
        session.add(
            AgentMemoryModel(
                id=record.id,
                workspace_key=record.workspace_key,
                category=record.category.value,
                summary=record.summary,
                tags=record.tags,
                outcome=record.outcome,
                flagged=record.flagged,
            )
        )
    session.flush()


def search(
    session: Session, *, workspace_key: str, query_text: str, limit: int = 5
) -> list[MemoryRecord]:
    """Simpel, forklarlig keyword-overlap-søgning — ingen embeddings/vector-DB.

    Bevidst valg: memory-mængden pr. workspace er lille (hundreder, ikke
    millioner, af rækker), så en Python-side scoring er hurtig nok og undgår
    en ny afhængighed. Flagged (mulige injection-forsøg) rækker udelukkes
    ALTID — fail closed, se agentops.memory.sanitize.
    """
    stmt = select(AgentMemoryModel).where(
        AgentMemoryModel.workspace_key == workspace_key,
        AgentMemoryModel.flagged.is_(False),
    )
    rows = list(session.scalars(stmt))
    query_tokens = _tokenize(query_text)

    scored: list[tuple[int, AgentMemoryModel]] = []
    for row in rows:
        row_tokens = _tokenize(row.summary) | {t.lower() for t in row.tags}
        overlap = len(query_tokens & row_tokens)
        if overlap > 0:
            scored.append((overlap, row))

    scored.sort(key=lambda pair: (pair[0], pair[1].created_at), reverse=True)
    return [_to_schema(row) for _, row in scored[:limit]]


def _tokenize(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_PATTERN.findall(text)}


def _to_schema(row: AgentMemoryModel) -> MemoryRecord:
    return MemoryRecord(
        id=row.id,
        workspace_key=row.workspace_key,
        category=MemoryCategory(row.category),
        summary=row.summary,
        tags=row.tags,
        outcome=row.outcome,
        flagged=row.flagged,
        created_at=row.created_at,
    )
