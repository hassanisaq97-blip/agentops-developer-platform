"""FastAPI dependency injection: henter app-niveau singletons fra `app.state`.

Gateway/orchestrator bygges én gang ved opstart (se `lifespan` i main.py) —
ikke per request — fordi provider-klienter (Anthropic/OpenAI SDK) er dyre at
initialisere og trygt kan genbruges på tværs af requests (de er stateless pr. kald).
"""

from __future__ import annotations

from collections.abc import Generator

from fastapi import Request
from sqlalchemy.orm import Session

from agentops.agent.multi_agent import MultiAgentOrchestrator
from agentops.agent.orchestrator import AgentOrchestrator
from agentops.gateway.gateway import LLMGateway
from agentops.gateway.schemas import ToolDefinition
from agentops.persistence.db import session_scope
from agentops.settings import Settings


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_gateway(request: Request) -> LLMGateway:
    return request.app.state.gateway


def get_orchestrator(request: Request) -> AgentOrchestrator:
    return request.app.state.orchestrator


def get_multi_agent_orchestrator(request: Request) -> MultiAgentOrchestrator:
    return request.app.state.multi_agent_orchestrator


def get_cached_tools(request: Request) -> list[ToolDefinition]:
    return request.app.state.tools_cache


def get_db_session() -> Generator[Session, None, None]:
    with session_scope() as session:
        yield session
