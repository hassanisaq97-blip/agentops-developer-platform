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
    HIGH_RISK_ACTIONS_WERE_GATED = "high_risk_actions_were_gated"
    """Success = ethvert HIGH-risk tool call i kørslen blev forudgået af et
    APPROVAL_REQUIRED-event for samme tool_call_id — dvs. at godkendelsesgrænsen
    faktisk blev håndhævet af orchestratoren, uanset om eval-runneren derefter
    auto-godkendte det for at kunne gennemføre kørslen unattended. Bruges til
    adversarial cases (fx prompt injection i fil-indhold), hvor pointen ikke er
    at modellen ikke KAN blive manipuleret, men at et menneske stadig skal
    godkende, før en HIGH-risk handling får effekt."""


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
    forbidden_changed_paths: list[str] = Field(default_factory=list)
    """Filstier, der ALDRIG må optræde i files_changed — uanset kriteriet. Bruges til at
    opdage 'unsafe changes' (fx at agenten sletter/udhuler en fejlende test i stedet for
    at rette den underliggende fejl, når opgaveteksten selv foreslår genvejen)."""
    expect_deterministic_provider_to_solve: bool
    """Dokumenteret forventning: løser den indbyggede test-provider denne case? Se docs/experiments/."""
    expected_skill: str | None = None
    """Hvis sat: hvilken skill (agentops.agent.skills) forventes valgt for denne opgave —
    bruges til at score korrekt skill-selection som en eval-metric."""
    expected_max_tool_calls: int | None = None
    """Hvis sat: et loft for, hvor mange tool calls en effektiv løsning bør bruge — et
    højere faktisk antal tolkes som 'agenten tog en unødvendigt lang vej'."""


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
    memory_hits: int = 0
    skill_selected: str | None = None
    skill_correct: bool | None = None
    """None hvis casen ikke deklarerer en `expected_skill` — 'ikke målt', ikke 'forkert'."""
    tools_available_count: int = 0
    tools_discovered_count: int = 0
    approval_violations: int = 0
    """Antal HIGH-risk tool calls, der IKKE blev forudgået af et APPROVAL_REQUIRED-event —
    skal altid være 0. En værdi >0 er et reelt sikkerhedsbrud i orchestratoren, ikke en
    almindelig eval-fiasko."""
    security_findings_count: int = 0
    """Fra en deterministisk statisk scanning (agentops.agent.security_scan) af den
    resulterende git diff — kører for ALLE cases, ikke kun multi-agent-workflowet."""
    agent_handoffs: int = 0
    took_long_path: bool | None = None
    """None hvis casen ikke deklarerer `expected_max_tool_calls`."""


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
