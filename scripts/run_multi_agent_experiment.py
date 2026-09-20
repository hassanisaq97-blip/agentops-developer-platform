#!/usr/bin/env python3
"""Sammenligner SINGLE AGENT vs. MULTI-AGENT (Developer/Test/Security/Reviewer)
på den samme opgave — begge med auto-godkendelse, så begge kan gennemføres
unattended og sammenlignes ét-til-ét."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentops.agent.multi_agent import MultiAgentOrchestrator  # noqa: E402
from agentops.agent.orchestrator import AgentOrchestrator  # noqa: E402
from agentops.evaluation.cases import BENCHMARK_CASES  # noqa: E402
from agentops.evaluation.fixtures import prepare_workspace  # noqa: E402
from agentops.gateway.gateway import LLMGateway  # noqa: E402
from agentops.gateway.providers.test_provider import DeterministicTestProvider  # noqa: E402
from agentops.gateway.router import ModelRouter  # noqa: E402
from agentops.settings import Settings  # noqa: E402

RESULTS_PATH = (
    Path(__file__).resolve().parents[1] / "docs" / "experiments" / "multi-agent-results.json"
)


async def run_single_agent(case, workspace: Path, settings: Settings) -> dict:
    gateway = LLMGateway(
        {"test": DeterministicTestProvider()}, ModelRouter(settings), fallback_provider=None
    )
    orchestrator = AgentOrchestrator(gateway, settings)
    result = await orchestrator.run(case.description, workspace, complexity=case.complexity)
    return {
        "mode": "single_agent",
        "status": result.status.value,
        "agent_handoffs": result.agent_handoffs,
        "total_tool_calls": result.total_tool_calls,
        "tests_passed": result.tests_passed,
        "tests_failed": result.tests_failed,
        "latency_ms": round(result.total_latency_ms, 2),
        "input_tokens": result.total_usage.input_tokens,
        "output_tokens": result.total_usage.output_tokens,
    }


async def run_multi_agent(case, workspace: Path, settings: Settings) -> dict:
    gateway = LLMGateway(
        {"test": DeterministicTestProvider()}, ModelRouter(settings), fallback_provider=None
    )
    workflow = MultiAgentOrchestrator(gateway, settings)
    result = await workflow.run(case.description, workspace, complexity=case.complexity)
    total_tool_calls = sum(p.tool_calls for p in result.phases)
    return {
        "mode": "multi_agent",
        "status": result.status.value,
        "final_verdict": result.final_verdict,
        "agent_handoffs": result.agent_handoffs,
        "total_tool_calls": total_tool_calls,
        "tests_passed": result.tests_passed,
        "tests_failed": result.tests_failed,
        "latency_ms": round(result.total_latency_ms, 2),
        "input_tokens": result.total_usage.input_tokens,
        "output_tokens": result.total_usage.output_tokens,
        "phases": [p.role.value for p in result.phases],
    }


async def main() -> None:
    case = next(c for c in BENCHMARK_CASES if c.id == "fix_failing_test_add")
    settings = Settings(llm_default_provider="test", agent_auto_approve_high_risk=True)

    with tempfile.TemporaryDirectory(prefix="agentops-multi-agent-experiment-") as tmp:
        tmp_dir = Path(tmp)
        single = await run_single_agent(
            case, prepare_workspace(case.fixture, tmp_dir / "single"), settings
        )
        multi = await run_multi_agent(
            case, prepare_workspace(case.fixture, tmp_dir / "multi"), settings
        )

    output = {"case_id": case.id, "single_agent": single, "multi_agent": multi}
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(output, indent=2), encoding="utf-8")

    print(f"Case: {case.id}\n")
    for label, r in (("SINGLE AGENT", single), ("MULTI-AGENT", multi)):
        print(
            f"{label:<14} status={r['status']:<12} handoffs={r['agent_handoffs']} "
            f"tool_calls={r['total_tool_calls']} tests={r['tests_passed']}/"
            f"{(r['tests_passed'] or 0) + (r['tests_failed'] or 0)} "
            f"tokens(in/out)={r['input_tokens']}/{r['output_tokens']}"
        )
    print(f"\nGemt til {RESULTS_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
