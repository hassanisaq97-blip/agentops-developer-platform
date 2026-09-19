"""Definition af benchmark-cases.

Hver case har en dokumenteret forventning til, om den indbyggede
deterministiske test-provider kan løse den. Dette er bevidst: den
deterministiske provider genkender kun ét bug-mønster (`return X - Y`), så
et par cases er designet til at fejle med den — det viser, at
success-kriterierne rent faktisk måler noget, i stedet for altid at returnere
"success" uanset input. Se docs/experiments/lessons-learned.md.
"""

from __future__ import annotations

from agentops.evaluation.schemas import EvalCase, SuccessCriterion

BENCHMARK_CASES: list[EvalCase] = [
    EvalCase(
        id="fix_failing_test_add",
        description="Find årsagen til, at tests/test_calculator.py fejler, og ret fejlen i src/calculator.py.",
        fixture="fix_failing_test_add",
        criterion=SuccessCriterion.TESTS_PASS,
        expected_max_changed_files=1,
        expect_deterministic_provider_to_solve=True,
    ),
    EvalCase(
        id="fix_failing_test_format",
        description="Find årsagen til, at tests/test_formatter.py fejler, og ret fejlen i src/formatter.py.",
        fixture="fix_failing_test_format",
        criterion=SuccessCriterion.TESTS_PASS,
        expected_max_changed_files=1,
        expect_deterministic_provider_to_solve=False,
    ),
    EvalCase(
        id="find_auth_function",
        description="Find den funktion, der håndterer authentication i dette repository, og angiv filstien.",
        fixture="find_auth_function",
        criterion=SuccessCriterion.TOOL_ARGUMENT_CONTAINS,
        criterion_target="auth.py",
        expected_max_changed_files=0,
        expect_deterministic_provider_to_solve=False,
    ),
    EvalCase(
        id="explain_report_module",
        description="Forklar hvad modulet src/report.py gør, uden at ændre nogen filer.",
        fixture="explain_report_module",
        criterion=SuccessCriterion.FILE_READ_BEFORE_ANSWER,
        criterion_target="src/report.py",
        expected_max_changed_files=0,
        expect_deterministic_provider_to_solve=False,
    ),
]
