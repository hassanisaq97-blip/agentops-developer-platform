"""Kører hele benchmark-suiten mod den deterministiske provider og verificerer,
at de dokumenterede forventninger i cases.py rent faktisk holder.

Dette er den vigtigste test af evalueringsframeworket: den beviser, at
success-kriterierne måler noget virkeligt (nogle cases lykkes, andre fejler
som forventet) i stedet for altid at returnere det samme.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentops.agent.orchestrator import AgentOrchestrator
from agentops.evaluation.cases import BENCHMARK_CASES
from agentops.evaluation.runner import EvalRunner
from agentops.gateway.gateway import LLMGateway
from agentops.gateway.providers.test_provider import DeterministicTestProvider
from agentops.gateway.router import ModelRouter
from agentops.settings import Settings


def _build_runner() -> EvalRunner:
    settings = Settings(llm_default_provider="test")
    gateway = LLMGateway(
        {"test": DeterministicTestProvider()}, ModelRouter(settings), fallback_provider=None
    )
    orchestrator = AgentOrchestrator(gateway, settings)
    return EvalRunner(orchestrator, settings)


@pytest.mark.integration
async def test_all_cases_match_their_documented_expectation():
    runner = _build_runner()
    summary = await runner.run_all(BENCHMARK_CASES)

    mismatches = [r for r in summary.case_results if not r.matched_expectation]
    assert mismatches == [], (
        f"Uventede resultater: {[(m.case_id, m.metrics.success) for m in mismatches]}"
    )


@pytest.mark.integration
async def test_success_rate_is_not_trivially_zero_or_one():
    """Hvis alle cases lykkes eller alle fejler, måler kriterierne formentlig ikke noget reelt."""
    runner = _build_runner()
    summary = await runner.run_all(BENCHMARK_CASES)

    assert 0.0 < summary.success_rate < 1.0, (
        f"Success rate {summary.success_rate} er mistænkeligt — forventede en blanding af succes/fejl."
    )


@pytest.mark.integration
async def test_solvable_case_actually_changes_exactly_one_file(tmp_path: Path):
    runner = _build_runner()
    result = await runner.run_case(BENCHMARK_CASES[0], workdir=tmp_path)
    assert result.metrics.success is True
    assert result.metrics.files_changed_count == 1
    assert result.metrics.unnecessary_files_changed == 0


@pytest.mark.integration
async def test_unsolvable_bugfix_case_leaves_files_unchanged(tmp_path: Path):
    runner = _build_runner()
    case = next(c for c in BENCHMARK_CASES if c.id == "fix_failing_test_format")
    result = await runner.run_case(case, workdir=tmp_path)
    assert result.metrics.success is False
    assert result.metrics.files_changed_count == 0
