"""GET /tools — hvilke developer tools kan agenten bruge, og hvor risikable er de?"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from agentops.agent.risk import risk_level_for
from agentops.api.dependencies import get_cached_tools
from agentops.api.schemas import ToolInfo
from agentops.gateway.schemas import ToolDefinition

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("", response_model=list[ToolInfo])
async def list_tools(tools: list[ToolDefinition] = Depends(get_cached_tools)) -> list[ToolInfo]:
    return [
        ToolInfo(name=t.name, description=t.description, risk_level=risk_level_for(t.name))
        for t in tools
    ]
