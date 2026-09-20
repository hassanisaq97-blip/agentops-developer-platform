#!/usr/bin/env python3
"""Sammenligner UDEN memory vs. MED memory på den samme opgave, kørt to gange
i det samme workspace (samme mønster som run_context_experiment.py).

Bruger en midlertidig SQLite-database, så eksperimentet er selvstændigt og
ikke rører den rigtige applikationsdatabase.

VIGTIGT: den deterministiske test-provider reagerer KUN på strukturerede
tool-resultater, aldrig på fritekst i system-prompten — den kan derfor
strukturelt ikke "bruge" den memory, der bliver injiceret i prompten, til at
tage færre tool calls eller lykkes oftere. Det, dette eksperiment FAKTISK
måler, er selve mekanikken: bliver relevant memory rent faktisk hentet og
gemt korrekt på tværs af to kørsler i samme workspace? Se
docs/experiments/lessons-learned.md og ADR-0013 for hvorfor en adfærdsmæssig
effekt af memory-indhold kræver en rigtig LLM at måle ærligt.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentops.agent.orchestrator import AgentOrchestrator  # noqa: E402
from agentops.evaluation.cases import BENCHMARK_CASES  # noqa: E402
from agentops.evaluation.fixtures import prepare_workspace  # noqa: E402
from agentops.gateway.gateway import LLMGateway  # noqa: E402
from agentops.gateway.providers.test_provider import DeterministicTestProvider  # noqa: E402
from agentops.gateway.router import ModelRouter  # noqa: E402
from agentops.memory import store  # noqa: E402
from agentops.memory.schemas import workspace_key_for  # noqa: E402
from agentops.persistence import db  # noqa: E402
from agentops.settings import Settings  # noqa: E402

RESULTS_PATH = Path(__file__).resolve().parents[1] / "docs" / "experiments" / "memory-results.json"


async def _run_once(orchestrator: AgentOrchestrator, case, workspace: Path) -> dict:
    result = await orchestrator.run(case.description, workspace, complexity=case.complexity)
    guard = 0
    while result.status.value == "awaiting_approval" and guard < 10:
        result = await orchestrator.resume(
            case.description,
            workspace,
            result.conversation_state,
            result.pending_approval,
            approved=True,
            complexity=case.complexity,
            prior_events=result.events,
            memory_hits=result.memory_hits,
        )
        guard += 1
    return {
        "status": result.status.value,
        "memory_hits": result.memory_hits,
        "total_tool_calls": result.total_tool_calls,
        "tests_passed": result.tests_passed,
        "tests_failed": result.tests_failed,
        "latency_ms": round(result.total_latency_ms, 2),
        "input_tokens": result.total_usage.input_tokens,
        "output_tokens": result.total_usage.output_tokens,
    }


async def run_condition(with_memory: bool, case, tmp_dir: Path) -> list[dict]:
    tmp_dir.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        llm_default_provider="test", database_url=f"sqlite:///{tmp_dir}/memory_exp.db"
    )
    db.init_engine(settings)
    db.create_all_tables()

    gateway = LLMGateway(
        {"test": DeterministicTestProvider()}, ModelRouter(settings), fallback_provider=None
    )

    if with_memory:

        async def retriever(workspace_key: str, query: str):
            with db.session_scope() as session:
                return store.search(session, workspace_key=workspace_key, query_text=query)

        async def saver(workspace_key: str, task: str, result):
            from agentops.memory.extraction import extract_memories

            records = extract_memories(
                workspace_key=workspace_key, task_description=task, result=result
            )
            with db.session_scope() as session:
                store.save(session, records)

        orchestrator = AgentOrchestrator(
            gateway, settings, memory_retriever=retriever, memory_saver=saver
        )
    else:
        orchestrator = AgentOrchestrator(gateway, settings)

    workspace = prepare_workspace(case.fixture, tmp_dir / f"ws-{with_memory}")
    workspace_key = workspace_key_for(str(workspace))

    run1 = await _run_once(orchestrator, case, workspace)
    with db.session_scope() as session:
        stored_after_run1 = len(
            store.search(session, workspace_key=workspace_key, query_text=case.description)
        )

    # Nulstil workspacet til dets oprindelige (buggy) tilstand, MEN på PRÆCIS samme
    # sti — memory er nøglet på workspace-stien (workspace_key_for), så en ny sti
    # ville (korrekt) ikke have nogen tidligere erfaring at hente.
    prepare_workspace(case.fixture, workspace)
    run2 = await _run_once(orchestrator, case, workspace)

    return [
        {**run1, "run": 1, "memories_in_store_after_run": stored_after_run1},
        {**run2, "run": 2},
    ]


async def main() -> None:
    case = next(c for c in BENCHMARK_CASES if c.id == "fix_failing_test_add")

    with tempfile.TemporaryDirectory(prefix="agentops-memory-experiment-") as tmp:
        tmp_dir = Path(tmp)
        without_memory = await run_condition(False, case, tmp_dir / "without")
        with_memory = await run_condition(True, case, tmp_dir / "with")

    output = {"case_id": case.id, "without_memory": without_memory, "with_memory": with_memory}
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(output, indent=2), encoding="utf-8")

    print(f"Case: {case.id}\n")
    for label, runs in (("UDEN memory", without_memory), ("MED memory", with_memory)):
        print(f"-- {label} --")
        for r in runs:
            print(
                f"  run {r['run']}: status={r['status']:<20} memory_hits={r['memory_hits']} "
                f"tool_calls={r['total_tool_calls']} tests={r['tests_passed']}/"
                f"{(r['tests_passed'] or 0) + (r['tests_failed'] or 0)}"
            )
    print(f"\nGemt til {RESULTS_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
