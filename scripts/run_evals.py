#!/usr/bin/env python3
"""CLI til at køre benchmark-suiten og gemme et reproducerbart, machine-readable resultat.

Brug:
    python scripts/run_evals.py                  # kører med LLM_DEFAULT_PROVIDER fra .env/environment
    python scripts/run_evals.py --provider test   # tving den deterministiske provider (ingen API-nøgle nødvendig)

Resultatet gemmes under evals/results/<run_id>.json og udskrives som et
resumé på stdout. Se docs/experiments/ for hvordan resultater sammenlignes
på tværs af context-strategier og providers.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentops.agent.context import ContextStrategy  # noqa: E402
from agentops.agent.orchestrator import AgentOrchestrator  # noqa: E402
from agentops.evaluation.cases import BENCHMARK_CASES  # noqa: E402
from agentops.evaluation.runner import EvalRunner  # noqa: E402
from agentops.evaluation.storage import save_run  # noqa: E402
from agentops.gateway.factory import build_gateway  # noqa: E402
from agentops.settings import get_settings  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provider", default=None, help="Override LLM_DEFAULT_PROVIDER (fx 'test', 'anthropic')."
    )
    parser.add_argument(
        "--context-strategy",
        default=ContextStrategy.TARGETED_MCP.value,
        choices=[s.value for s in ContextStrategy],
        help="Context-strategi anvendt for alle cases i denne kørsel.",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    settings = get_settings()
    if args.provider:
        settings = settings.model_copy(update={"llm_default_provider": args.provider})

    gateway = build_gateway(settings)
    orchestrator = AgentOrchestrator(gateway, settings)
    runner = EvalRunner(orchestrator, settings)

    strategy = ContextStrategy(args.context_strategy)
    cases = [c.model_copy(update={"context_strategy": strategy}) for c in BENCHMARK_CASES]

    summary = await runner.run_all(cases)
    path = save_run(summary)

    print(f"Kørsel gemt: {path}")
    print(f"Provider: {settings.llm_default_provider} | Context-strategi: {strategy.value}")
    print(
        f"Success rate: {summary.success_rate:.0%}  ({sum(r.metrics.success for r in summary.case_results)}/{len(summary.case_results)})"
    )
    print(f"Forventning matchet: {summary.expectation_match_rate:.0%}")
    print(f"Gennemsnitligt antal tool calls: {summary.average_tool_calls:.1f}")
    print()
    for result in summary.case_results:
        status = "OK" if result.metrics.success else "FEJL"
        print(
            f"  [{status}] {result.case_id:<28} tool_calls={result.metrics.total_tool_calls:<3} "
            f"tests={result.metrics.tests_passed}/{(result.metrics.tests_passed or 0) + (result.metrics.tests_failed or 0)} "
            f"files_changed={result.metrics.files_changed_count}"
        )


if __name__ == "__main__":
    asyncio.run(main())
