#!/usr/bin/env python3
"""Sammenligner ALLE TOOLS (default) vs. DYNAMISK TOOL DISCOVERY på flere cases.

I modsætning til memory-eksperimentet er dette en af de FÅ ting, den
deterministiske test-provider genuint kan vise en adfærdsforskel på: hvilke
tool-navne der findes i `request.tools` afgør DIREKTE, hvilke grene af
`DeterministicTestProvider._next_step` der er tilgængelige (den tjekker
`tool_name in available`). Filtreres et nødvendigt tool væk, ser man en reel,
målt konsekvens — ikke kun en strukturel/håbet effekt.
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
from agentops.settings import Settings  # noqa: E402

RESULTS_PATH = (
    Path(__file__).resolve().parents[1] / "docs" / "experiments" / "tool-discovery-results.json"
)

CASE_IDS = [
    "fix_failing_test_add",
    "security_review_probe",
    "database_migration_review_probe",
    "api_review_probe",
]


async def run_one(case, dynamic_discovery: bool, tmp_dir: Path) -> dict:
    settings = Settings(llm_default_provider="test", agent_dynamic_tool_discovery=dynamic_discovery)
    gateway = LLMGateway(
        {"test": DeterministicTestProvider()}, ModelRouter(settings), fallback_provider=None
    )
    orchestrator = AgentOrchestrator(gateway, settings)
    workspace = prepare_workspace(case.fixture, tmp_dir / case.id)

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
        )
        guard += 1

    return {
        "case_id": case.id,
        "dynamic_discovery": dynamic_discovery,
        "status": result.status.value,
        "skill_selected": result.skill_selected,
        "tools_available_count": result.tools_available_count,
        "tools_discovered_count": result.tools_discovered_count,
        "total_tool_calls": result.total_tool_calls,
        "tests_passed": result.tests_passed,
        "tests_failed": result.tests_failed,
        "latency_ms": round(result.total_latency_ms, 2),
        "input_tokens": result.total_usage.input_tokens,
        "output_tokens": result.total_usage.output_tokens,
    }


async def main() -> None:
    cases = [c for c in BENCHMARK_CASES if c.id in CASE_IDS]
    results = []
    with tempfile.TemporaryDirectory(prefix="agentops-tool-discovery-experiment-") as tmp:
        tmp_dir = Path(tmp)
        for case in cases:
            results.append(await run_one(case, False, tmp_dir / "all"))
            results.append(await run_one(case, True, tmp_dir / "dynamic"))

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps({"results": results}, indent=2), encoding="utf-8")

    print(
        f"{'Case':<32} {'Discovery':<10} {'Tools':<10} {'ToolCalls':<10} "
        f"{'Tokens (in/out)':<18} {'Status'}"
    )
    for r in results:
        mode = "dynamic" if r["dynamic_discovery"] else "all"
        tools = f"{r['tools_discovered_count']}/{r['tools_available_count']}"
        tokens = f"{r['input_tokens']}/{r['output_tokens']}"
        print(
            f"{r['case_id']:<32} {mode:<10} {tools:<10} {r['total_tool_calls']:<10} "
            f"{tokens:<18} {r['status']}"
        )
    print(f"\nGemt til {RESULTS_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
