"""FastAPI-applikationen: eksponerer platformen som en HTTP-API.

`create_app(settings)` er en factory frem for et modul-niveau singleton, så
tests kan injicere isolerede settings (fx en SQLite-database pr. test) uden
at dele global state mellem testkørsler.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from agentops.agent.mcp_client import MCPClient
from agentops.agent.orchestrator import AgentOrchestrator
from agentops.api.routers import evaluations, health, tasks, tools
from agentops.gateway.factory import build_gateway
from agentops.memory.integration import retrieve_memories, save_memories
from agentops.observability.logging_config import configure_logging
from agentops.observability.tracing import configure_mlflow
from agentops.persistence import db, task_repository
from agentops.settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        configure_logging(settings.log_level)
        configure_mlflow(settings)
        db.init_engine(settings)
        db.run_migrations(settings)

        with db.session_scope() as session:
            recovered = task_repository.recover_interrupted_tasks(session)
        if recovered:
            logging.getLogger(__name__).warning(
                "recovered_interrupted_tasks", extra={"count": len(recovered)}
            )

        gateway = build_gateway(settings)
        app.state.settings = settings
        app.state.gateway = gateway
        app.state.orchestrator = AgentOrchestrator(
            gateway,
            settings,
            memory_retriever=retrieve_memories if settings.agent_memory_enabled else None,
            memory_saver=save_memories if settings.agent_memory_enabled else None,
        )

        async with MCPClient(str(settings.workspace_root)) as client:
            app.state.tools_cache = await client.list_tool_definitions()

        yield

    app = FastAPI(
        title="AgentOps Developer Platform",
        description="Observerbar og evaluerbar AI-platform til agent-assisteret softwareudvikling.",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.include_router(health.router)
    app.include_router(tasks.router)
    app.include_router(evaluations.router)
    app.include_router(tools.router)

    return app


app = create_app()
