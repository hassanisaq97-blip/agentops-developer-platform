"""Schemas for evalueringsframeworket.

Alle metrics her er DETERMINISTISKE — udledt af faktiske tool-kald og
faktiske testresultater, aldrig af et sprogmodels egen vurdering af sig selv.
Et eventuelt LLM-as-a-judge-lag ville tilføje et separat `subjective_score`-felt
og skal aldrig blandes ind i `success`, som denne fil definerer.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from agentops.agent.context import ContextStrategy
from agentops.gateway.schemas import TaskComplexity


class SuccessCriterion(StrEnum):
    TESTS_PASS = "tests_pass"
    """Success = testsuiten består efter agentens kørsel (og bestod ikke før)."""
    TOOL_ARGUMENT_CONTAINS = "tool_argument_contains"
    """Success = mindst ét read_file/search_code-kald refererede til `criterion_target`."""
    FILE_READ_BEFORE_ANSWER = "file_read_before_answer"
    """Success = `criterion_target` blev læst, før agenten gav sit afsluttende svar."""


class EvalCase(BaseModel):
    id: str
    description: str
    """Opgaveteksten, agenten får."""
    fixture: str
    """Mappenavn under evals/fixtures/."""
    criterion: SuccessCriterion
    criterion_target: str | None = None
    context_strategy: ContextStrategy = ContextStrategy.TARGETED_MCP
    complexity: TaskComplexity = TaskComplexity.SIMPLE
    expected_max_changed_files: int = 0
    """Forventet antal ændrede filer ved succes — bruges til at måle unødvendige ændringer."""
    expect_deterministic_provider_to_solve: bool
    """Dokumenteret forventning: løser den indbyggede test-provider denne case? Se docs/experiments/."""


class DeterministicMetrics(BaseModel):
    success: bool
    status: str
    tests_run: bool = False
    tests_passed: int | None = None
    tests_failed: int | None = None
    total_tool_calls: int = 0
    files_changed_count: int = 0
    unnecessary_files_changed: int = 0
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    used_fallback: bool = False
    error: str | None = None


class EvalCaseResult(BaseModel):
    case_id: str
    fixture: str
    provider: str
    model: str
    context_strategy: str
    metrics: DeterministicMetrics
    expected_success: bool
    matched_expectation: bool


class EvalRunSummary(BaseModel):
    run_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    provider: str
    model: str
    context_strategy: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    case_results: list[EvalCaseResult] = Field(default_factory=list)

    @property
    def success_rate(self) -> float:
        if not self.case_results:
            return 0.0
        return sum(1 for r in self.case_results if r.metrics.success) / len(self.case_results)

    @property
    def expectation_match_rate(self) -> float:
        """Hvor ofte målte resultater matchede den dokumenterede forventning — en regressions-indikator."""
        if not self.case_results:
            return 0.0
        return sum(1 for r in self.case_results if r.matched_expectation) / len(self.case_results)

    @property
    def average_tool_calls(self) -> float:
        if not self.case_results:
            return 0.0
        return sum(r.metrics.total_tool_calls for r in self.case_results) / len(self.case_results)
