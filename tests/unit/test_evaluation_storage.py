from agentops.evaluation.schemas import DeterministicMetrics, EvalCaseResult, EvalRunSummary
from agentops.evaluation.storage import compare_runs, list_runs, load_run, save_run


def _summary(success: bool) -> EvalRunSummary:
    return EvalRunSummary(
        provider="test",
        model="deterministic-v1",
        context_strategy="targeted_mcp",
        case_results=[
            EvalCaseResult(
                case_id="fix_failing_test_add",
                fixture="fix_failing_test_add",
                provider="test",
                model="deterministic-v1",
                context_strategy="targeted_mcp",
                metrics=DeterministicMetrics(success=success, status="completed"),
                expected_success=True,
                matched_expectation=success,
            )
        ],
    )


def test_save_and_load_roundtrip(tmp_path):
    summary = _summary(success=True)
    path = save_run(summary, results_root=tmp_path)
    loaded = load_run(path)
    assert loaded.run_id == summary.run_id
    assert loaded.case_results[0].case_id == "fix_failing_test_add"


def test_list_runs_returns_all_saved_runs(tmp_path):
    save_run(_summary(success=True), results_root=tmp_path)
    save_run(_summary(success=False), results_root=tmp_path)
    runs = list_runs(results_root=tmp_path)
    assert len(runs) == 2


def test_compare_runs_detects_regression(tmp_path):
    baseline = _summary(success=True)
    candidate = _summary(success=False)
    diff = compare_runs(baseline, candidate)
    assert diff["regressions"] == ["fix_failing_test_add"]
    assert diff["improvements"] == []


def test_compare_runs_detects_improvement(tmp_path):
    baseline = _summary(success=False)
    candidate = _summary(success=True)
    diff = compare_runs(baseline, candidate)
    assert diff["improvements"] == ["fix_failing_test_add"]
    assert diff["regressions"] == []
