#!/usr/bin/env python3
"""Reproducerbar demonstration af hele platformen, ende-til-ende.

Scenarie: `demo_repo/` indeholder en bevidst indsat bug (funktionen `add`
beregner `a - b` i stedet for `a + b`). Dette script:

  1. opretter en opgave via den faktiske FastAPI-API (samme kode som ville
     køre bag `uvicorn agentops.api.main:app`, ikke en forenklet variant)
  2. viser agenten undersøge repositoryet via MCP tools (get_repository_status,
     run_tests, search_code, read_file)
  3. viser at agenten identificerer buggen og foreslår en patch
  4. viser godkendelsestrinnet (høj-risiko handling kræver eksplicit approval)
  5. godkender ændringen og lader agenten anvende patchen
  6. viser at testsuiten består efter rettelsen
  7. udskriver den fulde, strukturerede trace

Brug: `python scripts/run_demo.py`. Kræver ingen API-nøgle (bruger den
deterministiske test-provider som standard) — sæt `LLM_DEFAULT_PROVIDER=anthropic`
og `ANTHROPIC_API_KEY` i miljøet for at køre demoen mod en rigtig model.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from agentops.api.main import create_app  # noqa: E402
from agentops.observability.tracing import mlflow  # noqa: E402
from agentops.settings import Settings, get_settings  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]


def _banner(text: str) -> None:
    print(f"\n{'=' * 70}\n{text}\n{'=' * 70}")


def _prepare_demo_workspace(tmp_dir: Path) -> Path:
    workspace = tmp_dir / "demo_repo"
    shutil.copytree(REPO_ROOT / "demo_repo", workspace)
    for cmd in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "demo@agentops.local"],
        ["git", "config", "user.name", "AgentOps Demo"],
        ["git", "add", "."],
        ["git", "commit", "-q", "-m", "initial demo repository state (with bug)"],
    ):
        subprocess.run(cmd, cwd=workspace, check=True)
    return workspace


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agentops-demo-") as tmp:
        tmp_path = Path(tmp)
        workspace = _prepare_demo_workspace(tmp_path)

        base_settings = get_settings()
        settings = Settings(
            database_url=f"sqlite:///{tmp_path}/demo.db",
            agent_workspace_root=str(workspace),
            mlflow_tracking_uri=f"sqlite:///{tmp_path}/mlflow.db",
            eval_results_root=str(tmp_path / "eval_results"),
            llm_default_provider=base_settings.llm_default_provider,
            anthropic_api_key=base_settings.anthropic_api_key,
            openai_api_key=base_settings.openai_api_key,
        )

        _banner("1. Opgave oprettes via POST /tasks")
        print(f"Workspace: {workspace}")
        print(f"LLM-provider: {settings.llm_default_provider}")

        app = create_app(settings)
        with TestClient(app) as client:
            task = client.post(
                "/tasks",
                json={"description": "Find årsagen til den fejlende test, og foreslå en rettelse."},
            ).json()
            task_id = task["id"]
            print(f"\nOpgave-id: {task_id}")
            print(f"Status: {task['status']}")

            _banner("2-6. Agenten undersøger repositoryet og foreslår en rettelse")
            trace = client.get(f"/tasks/{task_id}/trace").json()
            for event in trace["events"]:
                _print_event(event)

            if task["status"] == "awaiting_approval":
                _banner("7. Menneskelig godkendelse kræves")
                pending = task["pending_approval"]
                print(f"Tool: {pending['tool_name']} (risiko: {pending['risk_level']})")
                print(f"Argumenter: {pending['arguments']}")
                print("\n-> Godkender ændringen (POST /tasks/{id}/approve, approved=true) ...")

                task = client.post(f"/tasks/{task_id}/approve", json={"approved": True}).json()

                _banner("8-9. Ændringen anvendes, og tests køres igen")
                trace = client.get(f"/tasks/{task_id}/trace").json()
                for event in trace["events"][len(trace["events"]) - 3 :]:
                    _print_event(event)

            _banner("10. Resultat")
            print(f"Status: {task['status']}")
            print(f"Ændrede filer: {task['files_changed']}")
            print(f"Tests: {task['tests_passed']} bestået, {task['tests_failed']} fejlet")
            print(f"Afsluttende svar: {task['final_answer']}")

            _banner("Filens faktiske indhold efter rettelsen")
            print((workspace / "src" / "calculator.py").read_text())

            _banner("11. Fuld trace er tilgængelig via GET /tasks/{id}/trace")
            print(f"Antal events: {len(trace['events'])}")

        # Flush MLflow's asynkrone trace-kø, mens tmp-databasen stadig findes —
        # ellers logger den en (harmløs, men forvirrende) fejl efter tmp-oprydning.
        mlflow.flush_trace_async_logging()

        print(
            "\nDemo afsluttet. Intet blev ændret i det rigtige repository — kun i en midlertidig kopi."
        )


def _print_event(event: dict) -> None:
    kind = event["type"]
    if kind == "tool_call":
        print(f"  [tool_call]   {event['tool_name']}({event['arguments']})")
    elif kind == "tool_result":
        summary = (event["result_summary"] or "")[:150].replace("\n", " ")
        print(f"  [tool_result] {event['tool_name']}: {summary}")
    elif kind == "final_answer":
        print(f"  [final]       {event['result_summary']}")
    else:
        print(f"  [{kind}]")


if __name__ == "__main__":
    main()
