"""MLflow-tracing konfiguration og span-helpers.

Vi bruger MLflow's manual span-API (`mlflow.start_span`) frem for
`@mlflow.trace`-dekoratoren de steder, hvor vi eksplicit vil styre, hvad der
logges som input/output (fx redacted tool-arguments) i stedet for at lade
dekoratoren automatisk serialisere `self` og andre interne objekter.

En agent-kørsel bliver dermed én MLflow-trace med spans i denne form:

    agent_run (AGENT)
    ├── llm_call (LLM)          — første model-kald
    ├── tool:get_repository_status (TOOL)
    ├── llm_call (LLM)
    ├── tool:run_tests (TOOL)
    └── ...

Se docs/adr/0004-mlflow-observability.md for begrundelsen for MLflow frem for
et hjemmerullet logging-format.
"""

from __future__ import annotations

import os

os.environ.setdefault("MLFLOW_DISABLE_TELEMETRY", "true")
# Platformen har ingen legitim grund til at ringe hjem til MLflow's telemetri-endpoint,
# og i sandboxede/air-gapped miljøer fejler det blot som en støjende netværksfejl.

import mlflow  # noqa: E402
from mlflow.entities import SpanType  # noqa: E402

from agentops.settings import Settings, get_settings

__all__ = ["SpanType", "configure_mlflow", "mlflow"]

_configured = False


def configure_mlflow(settings: Settings | None = None) -> None:
    """Sætter tracking URI og experiment. Idempotent — kaldes typisk én gang ved opstart."""
    global _configured
    if _configured:
        return
    settings = settings or get_settings()
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    mlflow.set_experiment(settings.mlflow_experiment_name)
    _configured = True
