"""Kører persistence-laget mod en RIGTIG PostgreSQL-instans (ikke SQLite).

Springes over, hvis ingen PostgreSQL er tilgængelig på TEST_DATABASE_URL /
standard-porten — CI's unit-testjob kører fortsat mod SQLite (se
tests/unit/test_persistence.py), mens dette job kræver en Postgres-service
(se .github/workflows/ci.yml, jobbet `integration-tests`).
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from agentops.persistence import db, task_repository
from agentops.settings import Settings

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://agentops:agentops@127.0.0.1:5432/agentops"
)


def _postgres_available() -> bool:
    try:
        engine = create_engine(TEST_DATABASE_URL)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except OperationalError:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _postgres_available(), reason="Ingen PostgreSQL tilgængelig på TEST_DATABASE_URL"
    ),
]


@pytest.fixture
def pg_session():
    settings = Settings(database_url=TEST_DATABASE_URL)
    db.init_engine(settings)
    db.create_all_tables()
    with db.session_scope() as session:
        yield session
        # Ryd op efter os selv, så gentagne testkørsler ikke akkumulerer rækker.
        for table in ("approvals", "tasks", "evaluation_runs"):
            session.execute(text(f"DELETE FROM {table}"))


def test_create_and_fetch_task_against_real_postgres(pg_session):
    record = task_repository.create_task(
        pg_session,
        description="Real Postgres integration test",
        context_strategy="targeted_mcp",
        complexity="simple",
        workspace_root="/tmp/repo",
    )
    pg_session.commit()

    fetched = task_repository.get_task(pg_session, record.id)
    assert fetched is not None
    assert fetched.status == "running"
    assert fetched.description == "Real Postgres integration test"


def test_json_columns_roundtrip_through_real_postgres(pg_session):
    from agentops.agent.events import AgentEvent, AgentEventType
    from agentops.agent.schemas import AgentRunResult, TaskStatus
    from agentops.gateway.schemas import ChatRole, Message, TokenUsage

    record = task_repository.create_task(
        pg_session,
        description="JSON roundtrip",
        context_strategy="targeted_mcp",
        complexity="simple",
        workspace_root="/tmp",
    )
    result = AgentRunResult(
        status=TaskStatus.COMPLETED,
        task_summary="JSON roundtrip",
        final_answer="done",
        tools_used=["run_tests"],
        events=[AgentEvent(step=0, type=AgentEventType.FINAL_ANSWER, result_summary="done")],
        conversation_state=[Message(role=ChatRole.USER, content="JSON roundtrip")],
        total_usage=TokenUsage(input_tokens=5, output_tokens=5),
        provider="test",
        model="deterministic-v1",
    )
    task_repository.apply_agent_result(pg_session, record, result)
    pg_session.commit()

    fetched = task_repository.get_task(pg_session, record.id)
    conversation = task_repository.conversation_from_record(fetched)
    events = task_repository.events_from_record(fetched)
    assert conversation[0].content == "JSON roundtrip"
    assert events[0].result_summary == "done"
