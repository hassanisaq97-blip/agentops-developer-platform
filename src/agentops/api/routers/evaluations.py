"""Evaluation-endpoints: se tidligere kørsler, og udløs en ny.

Bemærk: POST /evaluations/run kører hele benchmark-suiten synkront inden for
requestet. Det er en bevidst forenkling — se docs/adr for afvejningen mod en
baggrunds-jobkø, som ville være nødvendig i en rigtig produktionsplatform med
mange/langsomme cases.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from agentops.agent.orchestrator import AgentOrchestrator
from agentops.api.converters import eval_summary_to_response
from agentops.api.dependencies import get_app_settings, get_orchestrator
from agentops.api.schemas import EvalRunResponse
from agentops.evaluation.cases import BENCHMARK_CASES
from agentops.evaluation.runner import EvalRunner
from agentops.evaluation.storage import RESULTS_ROOT, list_runs, save_run
from agentops.settings import Settings

router = APIRouter(prefix="/evaluations", tags=["evaluations"])


@router.get("", response_model=list[EvalRunResponse])
async def get_evaluations(settings: Settings = Depends(get_app_settings)) -> list[EvalRunResponse]:
    return [
        eval_summary_to_response(r)
        for r in list_runs(results_root=settings.resolved_eval_results_root or RESULTS_ROOT)
    ]


@router.post("/run", response_model=EvalRunResponse, status_code=status.HTTP_201_CREATED)
async def run_evaluations(
    orchestrator: AgentOrchestrator = Depends(get_orchestrator),
    settings: Settings = Depends(get_app_settings),
) -> EvalRunResponse:
    runner = EvalRunner(orchestrator, settings)
    summary = await runner.run_all(BENCHMARK_CASES)
    save_run(summary, results_root=settings.resolved_eval_results_root or RESULTS_ROOT)
    return eval_summary_to_response(summary)
