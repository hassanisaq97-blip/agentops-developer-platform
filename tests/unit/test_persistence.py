import pytest

from agentops.agent.events import AgentEvent, AgentEventType
from agentops.agent.risk import RiskLevel
from agentops.agent.schemas import AgentRunResult, PendingApproval, TaskStatus
from agentops.gateway.schemas import ChatRole, Message, TokenUsage
from agentops.persistence import db, task_repository
from agentops.settings import Settings


@pytest.fixture
def session(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path}/test.db")
    db.init_engine(settings)
    db.create_all_tables()
    with db.session_scope() as s:
        yield s


def _completed_result() -> AgentRunResult:
    return AgentRunResult(
        status=TaskStatus.COMPLETED,
        task_summary="Fix the bug",
        final_answer="Fixed it.",
        tools_used=["run_tests"],
        tests_run=True,
        tests_passed=1,
        tests_failed=0,
        events=[AgentEvent(step=0, type=AgentEventType.FINAL_ANSWER, result_summary="Fixed it.")],
        conversation_state=[Message(role=ChatRole.USER, content="Fix the bug")],
        total_usage=TokenUsage(input_tokens=100, output_tokens=20),
        total_latency_ms=42.0,
        provider="test",
        model="deterministic-v1",
    )


def test_create_and_fetch_task(session):
    record = task_repository.create_task(
        session,
        description="Fix the bug",
        context_strategy="targeted_mcp",
        complexity="simple",
        workspace_root="/tmp/repo",
    )
    fetched = task_repository.get_task(session, record.id)
    assert fetched is not None
    assert fetched.status == "running"


def test_apply_completed_result_persists_all_fields(session):
    record = task_repository.create_task(
        session,
        description="Fix the bug",
        context_strategy="targeted_mcp",
        complexity="simple",
        workspace_root="/tmp/repo",
    )
    task_repository.apply_agent_result(session, record, _completed_result())

    fetched = task_repository.get_task(session, record.id)
    assert fetched.status == "completed"
    assert fetched.tests_passed == 1
    assert fetched.total_input_tokens == 100
    conversation = task_repository.conversation_from_record(fetched)
    assert conversation[0].content == "Fix the bug"


def test_awaiting_approval_creates_pending_approval_record(session):
    record = task_repository.create_task(
        session,
        description="Fix the bug",
        context_strategy="targeted_mcp",
        complexity="simple",
        workspace_root="/tmp/repo",
    )
    result = _completed_result()
    result.status = TaskStatus.AWAITING_APPROVAL
    result.pending_approval = PendingApproval(
        tool_name="apply_patch", arguments={"diff_text": "..."}, risk_level=RiskLevel.HIGH
    )
    task_repository.apply_agent_result(session, record, result)

    pending = task_repository.get_pending_approval(session, record.id)
    assert pending is not None
    assert pending.tool_name == "apply_patch"

    schema = task_repository.to_pending_approval_schema(pending)
    assert schema.risk_level == RiskLevel.HIGH


def test_record_approval_decision_marks_approved(session):
    record = task_repository.create_task(
        session,
        description="Fix the bug",
        context_strategy="targeted_mcp",
        complexity="simple",
        workspace_root="/tmp/repo",
    )
    result = _completed_result()
    result.status = TaskStatus.AWAITING_APPROVAL
    result.pending_approval = PendingApproval(
        tool_name="apply_patch", arguments={}, risk_level=RiskLevel.HIGH
    )
    task_repository.apply_agent_result(session, record, result)

    pending = task_repository.get_pending_approval(session, record.id)
    task_repository.record_approval_decision(session, pending, approved=True)

    assert task_repository.get_pending_approval(session, record.id) is None


def test_run_migrations_creates_expected_tables(tmp_path):
    from sqlalchemy import inspect

    settings = Settings(database_url=f"sqlite:///{tmp_path}/migrated.db")
    db.run_migrations(settings)

    engine = db.build_engine(settings)
    tables = set(inspect(engine).get_table_names())
    assert {"tasks", "approvals", "evaluation_runs", "alembic_version"} <= tables


def test_list_tasks_orders_by_created_at_desc(session):
    task_repository.create_task(
        session,
        description="A",
        context_strategy="minimal",
        complexity="simple",
        workspace_root="/tmp",
    )
    task_repository.create_task(
        session,
        description="B",
        context_strategy="minimal",
        complexity="simple",
        workspace_root="/tmp",
    )
    tasks = task_repository.list_tasks(session)
    assert len(tasks) == 2
    assert tasks[0].description == "B"
