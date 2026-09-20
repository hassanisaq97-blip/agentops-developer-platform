"""End-to-end API-tests for /workflows — rigtig FastAPI TestClient, rigtig
SQLite-database, rigtig MCP-server-proces pr. fase."""

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
def client(tmp_path):
    workspace = _build_workspace(tmp_path)
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/api.db",
        agent_workspace_root=str(workspace),
        llm_default_provider="test",
        agent_auto_approve_high_risk=False,
        mlflow_tracking_uri=f"sqlite:///{tmp_path}/mlflow.db",
    )
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


@pytest.mark.integration
def test_workflow_pauses_then_approves_and_completes(client):
    create = client.post("/workflows", json={"description": "Find og ret den fejlende test."})
    assert create.status_code == 201
    body = create.json()
    assert body["status"] == "awaiting_approval"
    assert body["pending_approval"]["tool_calls"][0]["tool_name"] == "apply_patch"
    assert len(body["phases"]) == 1
    assert body["phases"][0]["role"] == "developer"
    workflow_id = body["id"]

    fetched = client.get(f"/workflows/{workflow_id}")
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "awaiting_approval"

    approve = client.post(f"/workflows/{workflow_id}/approve", json={"approved": True})
    assert approve.status_code == 200
    final = approve.json()
    assert final["status"] == "completed"
    assert final["final_verdict"] == "approved"
    assert [p["role"] for p in final["phases"]] == ["developer", "test", "security", "reviewer"]
    assert final["agent_handoffs"] == 4
    assert final["tests_passed"] is not None and final["tests_failed"] == 0
    assert "src/calculator.py" in final["files_changed"]


@pytest.mark.integration
def test_workflow_list_includes_created_workflow(client):
    create = client.post("/workflows", json={"description": "Find og ret den fejlende test."})
    workflow_id = create.json()["id"]

    listed = client.get("/workflows")
    assert listed.status_code == 200
    assert any(w["id"] == workflow_id for w in listed.json())


@pytest.mark.integration
def test_approving_unknown_workflow_returns_404(client):
    response = client.post(f"/workflows/{uuid.uuid4()}/approve", json={"approved": True})
    assert response.status_code == 404


@pytest.mark.integration
def test_approving_non_pending_workflow_returns_409(client):
    create = client.post("/workflows", json={"description": "Find og ret den fejlende test."})
    workflow_id = create.json()["id"]
    client.post(f"/workflows/{workflow_id}/approve", json={"approved": True})

    conflict = client.post(f"/workflows/{workflow_id}/approve", json={"approved": True})
    assert conflict.status_code == 409


@pytest.mark.integration
def test_unknown_repository_is_rejected_for_workflows(client):
    response = client.post("/workflows", json={"description": "x", "repository": "../../etc"})
    assert response.status_code == 400
