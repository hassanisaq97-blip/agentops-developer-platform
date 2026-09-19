"""Machine-readable persistence af evalueringsresultater, så runs kan sammenlignes over tid.

Gemmer hver `EvalRunSummary` som en selvstændig JSON-fil under
`evals/results/`. Dette er bevidst filbaseret og adskilt fra
`EvaluationRunRecord` i PostgreSQL (persistence/models.py): denne fil er
beregnet til at blive committet til Git (så CI's quality gate kan
sammenligne mod en baseline), mens databasen holder operationel state for
runs udløst via API'et.
"""

from __future__ import annotations

from pathlib import Path

from agentops.evaluation.schemas import EvalRunSummary

RESULTS_ROOT = Path(__file__).resolve().parents[3] / "evals" / "results"


def save_run(summary: EvalRunSummary, *, results_root: Path = RESULTS_ROOT) -> Path:
    results_root.mkdir(parents=True, exist_ok=True)
    path = results_root / f"{summary.run_id}.json"
    path.write_text(summary.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_run(path: Path) -> EvalRunSummary:
    return EvalRunSummary.model_validate_json(path.read_text(encoding="utf-8"))


def list_runs(*, results_root: Path = RESULTS_ROOT) -> list[EvalRunSummary]:
    if not results_root.is_dir():
        return []
    return [load_run(p) for p in sorted(results_root.glob("*.json"))]


def compare_runs(baseline: EvalRunSummary, candidate: EvalRunSummary) -> dict:
    """Sammenligner to runs pr. case — bruges til at opdage regressions mellem context-strategier/providers."""
    baseline_by_case = {r.case_id: r for r in baseline.case_results}
    candidate_by_case = {r.case_id: r for r in candidate.case_results}

    regressions = []
    improvements = []
    for case_id, candidate_result in candidate_by_case.items():
        baseline_result = baseline_by_case.get(case_id)
        if baseline_result is None:
            continue
        if baseline_result.metrics.success and not candidate_result.metrics.success:
            regressions.append(case_id)
        elif not baseline_result.metrics.success and candidate_result.metrics.success:
            improvements.append(case_id)

    return {
        "baseline_run_id": str(baseline.run_id),
        "candidate_run_id": str(candidate.run_id),
        "baseline_success_rate": baseline.success_rate,
        "candidate_success_rate": candidate.success_rate,
        "regressions": regressions,
        "improvements": improvements,
    }
