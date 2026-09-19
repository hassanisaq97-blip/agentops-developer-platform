#!/usr/bin/env python3
"""Sammenligner de fire context-strategier (A-D) på den samme opgave.

Kører "fix_failing_test_add"-casen under hver strategi og måler strukturelle,
reproducerbare tal: system-prompt-størrelse, antal tool calls, om opgaven
lykkedes, og estimeret token-forbrug. Resultatet gemmes som JSON under
docs/experiments/, og et resumé udskrives på stdout.

VIGTIGT: med den deterministiske test-provider måler dette kun strukturelle
forskelle (prompt-størrelse, tilgængelighed af tools) — IKKE om et
forudberegnet repository-resumé (strategi D) rent faktisk får en model til at
bruge færre exploratory tool calls. Det kræver ægte sprogmodel-ræsonnement og
er en dokumenteret begrænsning — se docs/experiments/lessons-learned.md.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentops.agent.context import ContextStrategy, build_system_prompt  # noqa: E402
from agentops.agent.orchestrator import AgentOrchestrator  # noqa: E402
from agentops.evaluation.cases import BENCHMARK_CASES  # noqa: E402
from agentops.evaluation.fixtures import prepare_workspace  # noqa: E402
from agentops.gateway.gateway import LLMGateway  # noqa: E402
from agentops.gateway.providers.test_provider import DeterministicTestProvider  # noqa: E402
from agentops.gateway.router import ModelRouter  # noqa: E402
from agentops.settings import Settings  # noqa: E402

RESULTS_PATH = (
    Path(__file__).resolve().parents[1] / "docs" / "experiments" / "context-strategy-results.json"
)


async def run_one(strategy: ContextStrategy, case, settings: Settings) -> dict:
    gateway = LLMGateway(
        {"test": DeterministicTestProvider()}, ModelRouter(settings), fallback_provider=None
    )
    orchestrator = AgentOrchestrator(gateway, settings)

    with tempfile.TemporaryDirectory(prefix="agentops-ctx-experiment-") as tmp:
        workspace = prepare_workspace(case.fixture, Path(tmp) / "w")
        prompt = build_system_prompt(strategy, workspace, case.description)

        result = await orchestrator.run(
            case.description, workspace, context_strategy=strategy, complexity=case.complexity
        )
        guard = 0
        while result.status.value == "awaiting_approval" and guard < 10:
            result = await orchestrator.resume(
                case.description,
                workspace,
                result.conversation_state,
                result.pending_approval,
                approved=True,
                context_strategy=strategy,
                complexity=case.complexity,
                prior_events=result.events,
            )
            guard += 1

        return {
            "strategy": strategy.value,
            "system_prompt_chars": len(prompt),
            "has_tools": strategy in {ContextStrategy.TARGETED_MCP, ContextStrategy.OPTIMIZED},
            "status": result.status.value,
            "total_tool_calls": result.total_tool_calls,
            "tools_used": result.tools_used,
            "tests_passed": result.tests_passed,
            "tests_failed": result.tests_failed,
            "input_tokens": result.total_usage.input_tokens,
            "output_tokens": result.total_usage.output_tokens,
        }


async def main() -> None:
    settings = Settings(llm_default_provider="test")
    case = BENCHMARK_CASES[
        0
    ]  # fix_failing_test_add — den eneste case, den deterministiske provider kan løse

    results = [await run_one(strategy, case, settings) for strategy in ContextStrategy]

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(
        json.dumps({"case_id": case.id, "results": results}, indent=2), encoding="utf-8"
    )

    print(f"Case: {case.id}\n")
    print(
        f"{'Strategi':<15} {'Prompt (chars)':<16} {'Tools?':<8} {'Status':<20} {'Tool calls':<12} {'Tests':<10}"
    )
    for r in results:
        tests = (
            f"{r['tests_passed']}/{(r['tests_passed'] or 0) + (r['tests_failed'] or 0)}"
            if r["tests_passed"] is not None
            else "-"
        )
        print(
            f"{r['strategy']:<15} {r['system_prompt_chars']:<16} {str(r['has_tools']):<8} "
            f"{r['status']:<20} {r['total_tool_calls']:<12} {tests:<10}"
        )
    print(f"\nGemt til {RESULTS_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
