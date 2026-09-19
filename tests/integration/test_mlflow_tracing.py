"""Verificerer at en agent-kørsel faktisk producerer en MLflow-trace med spans.

Følger verifikationsopskriften fra MLflow's egen
`instrumenting-with-mlflow-tracing`-skill: kør instrumenteret kode, flush den
asynkrone log-kø, og bekræft at traces og spans rent faktisk findes — i
stedet for blot at antage, at dekoratoren/spannet virker.
"""

from __future__ import annotations

import subprocess

import mlflow
import pytest

from agentops.agent.context import ContextStrategy
from agentops.agent.orchestrator import AgentOrchestrator
from agentops.gateway.gateway import LLMGateway
from agentops.gateway.providers.test_provider import DeterministicTestProvider
from agentops.gateway.router import ModelRouter
from agentops.settings import Settings


@pytest.fixture
def buggy_repo(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "calculator.py").write_text("def add(a, b):\n    return a - b\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_calculator.py").write_text(
        "import sys\nfrom pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))\n"
        "from calculator import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"
    )
    for cmd in (["git", "init", "-q"], ["git", "add", "."]):
        subprocess.run(cmd, cwd=tmp_path, check=True)
    return tmp_path


@pytest.mark.integration
async def test_agent_run_produces_an_mlflow_trace_with_expected_spans(
    tmp_path, buggy_repo, monkeypatch
):
    mlflow.set_tracking_uri(f"sqlite:///{tmp_path}/mlflow_test.db")
    experiment_name = "agentops-tracing-test"
    mlflow.set_experiment(experiment_name)

    settings = Settings(llm_default_provider="test", agent_auto_approve_high_risk=True)
    gateway = LLMGateway(
        {"test": DeterministicTestProvider()}, ModelRouter(settings), fallback_provider=None
    )
    orchestrator = AgentOrchestrator(gateway, settings)

    await orchestrator.run(
        "Find og ret den fejlende test.", buggy_repo, context_strategy=ContextStrategy.TARGETED_MCP
    )

    experiment = mlflow.get_experiment_by_name(experiment_name)
    traces = mlflow.search_traces(
        locations=[experiment.experiment_id], return_type="list", flush=True
    )

    assert len(traces) >= 1, "Ingen traces blev logget til MLflow — tracing virker ikke."

    spans = traces[0].data.spans
    span_names = [s.name for s in spans]

    assert any(name == "agent_run" for name in span_names), span_names
    assert any(name.startswith("llm_call:") for name in span_names), span_names
    assert any(name.startswith("tool:") for name in span_names), span_names
