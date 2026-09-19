"""End-to-end API-tests: rigtig FastAPI TestClient, rigtig SQLite-database, rigtig MCP-server-proces.

Kun LLM-kaldet er den deterministiske test-provider — alt andet (HTTP-laget,
databasen, MCP-protokollen, filsystemet) er reelt.
"""

from __future__ import annotations

import subprocess
import uuid

import pytest
from fastapi.testclient import TestClient

from agentops.api.main import create_app
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
def app_settings(tmp_path):
    workspace = _build_workspace(tmp_path)
    return Settings(
        database_url=f"sqlite:///{tmp_path}/api.db",
        agent_workspace_root=str(workspace),
        llm_default_provider="test",
        agent_auto_approve_high_risk=False,
        eval_results_root=str(tmp_path / "eval_results"),
        # Lokal fil-baseret tracking-URI: undgår et netværkskald mod en (i tests ikke-kørende)
        # MLflow-server, hvis default (http://localhost:5000) ellers ville få mlflow's
        # indbyggede retry-logik (op til ~7 forsøg / flere minutter) til at blokere opstart.
        mlflow_tracking_uri=f"sqlite:///{tmp_path}/mlflow.db",
    )


@pytest.fixture
def client(app_settings):
    app = create_app(app_settings)
    with TestClient(app) as c:
        yield c


@pytest.mark.integration
def test_health_and_ready(client):
    assert client.get("/health").json() == {"status": "ok"}
    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"


@pytest.mark.integration
def test_list_tools_reports_risk_levels(client):
    response = client.get("/tools")
    assert response.status_code == 200
    tools_by_name = {t["name"]: t for t in response.json()}
    assert tools_by_name["edit_file"]["risk_level"] == "high"
    assert tools_by_name["read_file"]["risk_level"] == "low"


@pytest.mark.integration
def test_create_task_pauses_for_approval_then_resumes(client):
    create = client.post("/tasks", json={"description": "Find og ret den fejlende test."})
    assert create.status_code == 201
    body = create.json()
    assert body["status"] == "awaiting_approval"
    assert body["pending_approval"]["tool_name"] == "apply_patch"
    task_id = body["id"]

    trace = client.get(f"/tasks/{task_id}/trace")
    assert trace.status_code == 200
    assert len(trace.json()["events"]) > 0

    approve = client.post(f"/tasks/{task_id}/approve", json={"approved": True})
    assert approve.status_code == 200
    approved_body = approve.json()
    assert approved_body["status"] == "completed"
    assert approved_body["tests_passed"] is not None
    assert approved_body["tests_failed"] == 0
    assert "src/calculator.py" in approved_body["files_changed"]


@pytest.mark.integration
def test_denying_approval_leaves_file_unchanged(client, app_settings):
    create = client.post("/tasks", json={"description": "Find og ret den fejlende test."})
    task_id = create.json()["id"]

    approve = client.post(f"/tasks/{task_id}/approve", json={"approved": False})
    assert approve.status_code == 200

    content = (app_settings.workspace_root / "src" / "calculator.py").read_text()
    assert "return a - b" in content


@pytest.mark.integration
def test_get_unknown_task_returns_404(client):
    response = client.get(f"/tasks/{uuid.uuid4()}")
    assert response.status_code == 404


@pytest.mark.integration
def test_approving_non_pending_task_returns_409(client):
    create = client.post("/tasks", json={"description": "Find og ret den fejlende test."})
    task_id = create.json()["id"]
    client.post(f"/tasks/{task_id}/approve", json={"approved": True})  # completes the task

    conflict = client.post(f"/tasks/{task_id}/approve", json={"approved": True})
    assert conflict.status_code == 409


@pytest.mark.integration
def test_unknown_repository_is_rejected(client):
    response = client.post("/tasks", json={"description": "x", "repository": "../../etc"})
    assert response.status_code == 400


@pytest.mark.integration
def test_evaluation_run_and_list(client):
    run_response = client.post("/evaluations/run")
    assert run_response.status_code == 201
    body = run_response.json()
    assert 0.0 <= body["success_rate"] <= 1.0
    assert len(body["case_results"]) == 4

    list_response = client.get("/evaluations")
    assert list_response.status_code == 200
    assert any(r["run_id"] == body["run_id"] for r in list_response.json())
