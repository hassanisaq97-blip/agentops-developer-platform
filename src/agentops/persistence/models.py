"""Applikations-state (SQLAlchemy-modeller).

Adskillelse fra observability: MLflow ejer tværgående analyse af traces
(sammenligning af latency/token usage/tool-brug på tværs af mange kørsler).
Denne database ejer operationel state for platformen: hvad er status på en
opgave lige nu, hvilke godkendelser afventer, og hvad blev der målt i en
evalueringskørsel. `Task.events_json` er en bevidst afgrænset undtagelse: en
kopi af de samme events, der også sendes til MLflow, gemmes her udelukkende
for at kunne betjene `/tasks/{id}/trace` uden en afhængighed af, at MLflow
tracking-serveren er oppe — se docs/adr/0004-mlflow-observability.md.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agentops.persistence.db import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ApprovalDecision(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


class TaskRecord(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32))
    context_strategy: Mapped[str] = mapped_column(String(32))
    complexity: Mapped[str] = mapped_column(String(16))
    workspace_root: Mapped[str] = mapped_column(String(512))

    final_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    used_fallback: Mapped[bool] = mapped_column(default=False)

    tools_used: Mapped[list] = mapped_column(JSON, default=list)
    files_examined: Mapped[list] = mapped_column(JSON, default=list)
    files_changed: Mapped[list] = mapped_column(JSON, default=list)
    tests_run: Mapped[bool] = mapped_column(default=False)
    tests_passed: Mapped[int | None] = mapped_column(nullable=True)
    tests_failed: Mapped[int | None] = mapped_column(nullable=True)
    warnings: Mapped[list] = mapped_column(JSON, default=list)

    conversation_state: Mapped[list] = mapped_column(JSON, default=list)
    """Operationel state — nødvendig for at kunne genoptage kørslen efter en godkendelse."""
    events_json: Mapped[list] = mapped_column(JSON, default=list)
    """Se modul-docstring: bevidst begrænset duplikering af trace-events for offline API-visning."""

    total_input_tokens: Mapped[int] = mapped_column(default=0)
    total_output_tokens: Mapped[int] = mapped_column(default=0)
    total_latency_ms: Mapped[float] = mapped_column(default=0.0)
    mlflow_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    approvals: Mapped[list[ApprovalRecord]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )


class ApprovalRecord(Base):
    __tablename__ = "approvals"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"))
    tool_name: Mapped[str] = mapped_column(String(64))
    arguments_json: Mapped[dict] = mapped_column(JSON, default=dict)
    risk_level: Mapped[str] = mapped_column(String(16))
    # native_enum=False: gemmes som VARCHAR i stedet for en Postgres CREATE TYPE-enum.
    # En native Postgres-enum kræver eksplicit DROP TYPE-håndtering i Alembic-downgrades
    # (et kendt fald­grube-mønster) — VARCHAR er enklere og identisk på tværs af SQLite/Postgres.
    decision: Mapped[str] = mapped_column(
        Enum(ApprovalDecision, native_enum=False, length=16), default=ApprovalDecision.PENDING
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    task: Mapped[TaskRecord] = relationship(back_populates="approvals")


class EvaluationRunRecord(Base):
    __tablename__ = "evaluation_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128))
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    context_strategy: Mapped[str] = mapped_column(String(32))
    summary_json: Mapped[dict] = mapped_column(JSON, default=dict)
    """Aggregerede, deterministiske metrics (success rate, gennemsnitligt tool-antal osv.)."""
    case_results_json: Mapped[list] = mapped_column(JSON, default=list)
    """Per-case resultater — se agentops.evaluation.schemas.EvalCaseResult."""
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
