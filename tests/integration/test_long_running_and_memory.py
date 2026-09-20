"""End-to-end tests for agent-memory og long-running/checkpoint-agenter — rigtig
FastAPI TestClient, rigtig SQLite-database, rigtig MCP-server-subprocess. Kun
LLM-kaldet er den deterministiske test-provider."""

from __future__ import annotations

import subprocess
import uuid

import pytest
from fastapi.testclient import TestClient

from agentops.api.main import create_app
from agentops.persistence import db, task_repository
from agentops.persistence.models import TaskRecord
from agentops.settings import Settings


def _build_workspace(tmp_path):
    workspace = tmp_path / "repo"
    (workspace / "src").mkdir(parents=True)
    (workspace / "src" / "calculator.py").write_text("def add(a, b):\n    return a - b\n")
    (workspace / "tests").mkdir()
    (workspace / "tests" / "test_calculator.py").write_text(
        "import sys\nfrom pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))\n"
        "from calculator import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"
    )
    for cmd in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "test@example.com"],
        ["git", "config", "user.name", "Test"],
        ["git", "add", "."],
        ["git", "commit", "-q", "-m", "init"],
    ):
        subprocess.run(cmd, cwd=workspace, check=True)
    return workspace


@pytest.fixture
def memory_settings(tmp_path):
    workspace = _build_workspace(tmp_path)
    return Settings(
        database_url=f"sqlite:///{tmp_path}/api.db",
        agent_workspace_root=str(workspace),
        llm_default_provider="test",
        agent_auto_approve_high_risk=True,
        agent_memory_enabled=True,
        mlflow_tracking_uri=f"sqlite:///{tmp_path}/mlflow.db",
    )


@pytest.mark.integration
def test_memory_is_retrieved_on_a_second_task_in_the_same_workspace(memory_settings):
    app = create_app(memory_settings)
    with TestClient(app) as client:
        first = client.post("/tasks", json={"description": "Find og ret den fejlende test."})
        assert first.status_code == 201
        assert first.json()["status"] == "completed"
        assert first.json()["memory_hits"] == 0  # intet at hente første gang

        second = client.post("/tasks", json={"description": "Find og ret den fejlende test."})
        assert second.status_code == 201
        assert second.json()["memory_hits"] > 0


@pytest.mark.integration
def test_memory_is_not_used_when_disabled(tmp_path):
    workspace = _build_workspace(tmp_path)
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/api.db",
        agent_workspace_root=str(workspace),
        llm_default_provider="test",
        agent_auto_approve_high_risk=True,
        agent_memory_enabled=False,
        mlflow_tracking_uri=f"sqlite:///{tmp_path}/mlflow.db",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        client.post("/tasks", json={"description": "Find og ret den fejlende test."})
        second = client.post("/tasks", json={"description": "Find og ret den fejlende test."})
        assert second.json()["memory_hits"] == 0


@pytest.mark.integration
def test_recovery_marks_running_task_with_checkpoint_as_paused(tmp_path):
    workspace = _build_workspace(tmp_path)
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/recover.db", agent_workspace_root=str(workspace)
    )
    db.init_engine(settings)
    db.run_migrations(settings)

    with db.session_scope() as session:
        record = task_repository.create_task(
            session,
            description="Langvarig opgave, afbrudt midt i.",
            context_strategy="targeted_mcp",
            complexity="simple",
            workspace_root=str(workspace),
        )
        record.conversation_state = [{"role": "user", "content": "Langvarig opgave"}]
        record.events_json = [{"step": 0, "type": "task_started"}]
        session.flush()
        task_id = record.id

    with db.session_scope() as session:
        recovered = task_repository.recover_interrupted_tasks(session)
        assert len(recovered) == 1
        assert recovered[0].id == task_id

    with db.session_scope() as session:
        record = session.get(TaskRecord, task_id)
        assert record.status == "paused"
        assert any("Gendannet" in w for w in record.warnings)


@pytest.mark.integration
def test_recovery_marks_running_task_without_checkpoint_as_failed(tmp_path):
    workspace = _build_workspace(tmp_path)
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/recover2.db", agent_workspace_root=str(workspace)
    )
    db.init_engine(settings)
    db.run_migrations(settings)

    with db.session_scope() as session:
        record = task_repository.create_task(
            session,
            description="Opgave, der aldrig nåede et checkpoint.",
            context_strategy="targeted_mcp",
            complexity="simple",
            workspace_root=str(workspace),
        )
        task_id = record.id

    with db.session_scope() as session:
        task_repository.recover_interrupted_tasks(session)

    with db.session_scope() as session:
        record = session.get(TaskRecord, task_id)
        assert record.status == "failed"


@pytest.mark.integration
def test_continue_endpoint_resumes_a_checkpoint_paused_task_to_completion(tmp_path):
    workspace = _build_workspace(tmp_path)
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/api.db",
        agent_workspace_root=str(workspace),
        llm_default_provider="test",
        agent_auto_approve_high_risk=True,
        agent_checkpoint_every_n_steps=1,
        mlflow_tracking_uri=f"sqlite:///{tmp_path}/mlflow.db",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        create = client.post("/tasks", json={"description": "Find og ret den fejlende test."})
        assert create.status_code == 201
        task_id = create.json()["id"]
        assert create.json()["status"] == "paused"

        guard = 0
        body = create.json()
        while body["status"] == "paused" and guard < 20:
            resp = client.post(f"/tasks/{task_id}/continue")
            assert resp.status_code == 200
            body = resp.json()
            guard += 1

        assert body["status"] == "completed"
        assert body["tests_passed"] is not None and body["tests_failed"] == 0
        assert "src/calculator.py" in body["files_changed"]


@pytest.mark.integration
def test_continuing_a_non_paused_task_returns_409(memory_settings):
    app = create_app(memory_settings)
    with TestClient(app) as client:
        create = client.post("/tasks", json={"description": "Find og ret den fejlende test."})
        task_id = create.json()["id"]
        assert create.json()["status"] == "completed"

        response = client.post(f"/tasks/{task_id}/continue")
        assert response.status_code == 409


@pytest.mark.integration
def test_continuing_unknown_task_returns_404(memory_settings):
    app = create_app(memory_settings)
    with TestClient(app) as client:
        response = client.post(f"/tasks/{uuid.uuid4()}/continue")
        assert response.status_code == 404
