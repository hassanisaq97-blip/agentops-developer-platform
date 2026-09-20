"""Forbinder det session-parameteriserede `agentops.memory.store` til de plain
async callables, `AgentOrchestrator` forventer (`memory_retriever`/`memory_saver`).

Holdt ude af `agentops.agent.orchestrator`, så orchestratoren aldrig behøver
importere SQLAlchemy eller `session_scope` — samme separation som API-laget
allerede holder over for `task_repository`.
"""

from __future__ import annotations

from agentops.agent.schemas import AgentRunResult
from agentops.memory import store
from agentops.memory.extraction import extract_memories
from agentops.memory.schemas import MemoryRecord, workspace_key_for
from agentops.observability.tracing import SpanType, mlflow
from agentops.persistence.db import session_scope

__all__ = ["retrieve_memories", "save_memories", "workspace_key_for"]


async def retrieve_memories(workspace_key: str, query_text: str) -> list[MemoryRecord]:
    with mlflow.start_span(name="memory_retrieval", span_type=SpanType.MEMORY) as span:
        span.set_inputs({"workspace_key": workspace_key, "query": query_text[:200]})
        with session_scope() as session:
            results = store.search(session, workspace_key=workspace_key, query_text=query_text)
        span.set_outputs({"hits": len(results), "categories": [r.category.value for r in results]})
        return results


async def save_memories(workspace_key: str, task_description: str, result: AgentRunResult) -> None:
    records = extract_memories(
        workspace_key=workspace_key, task_description=task_description, result=result
    )
    with mlflow.start_span(name="memory_store", span_type=SpanType.MEMORY) as span:
        span.set_inputs({"workspace_key": workspace_key, "candidate_count": len(records)})
        with session_scope() as session:
            store.save(session, records)
        span.set_outputs(
            {
                "stored": len(records),
                "flagged": sum(1 for r in records if r.flagged),
            }
        )
