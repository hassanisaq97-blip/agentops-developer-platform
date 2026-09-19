"""MCP-klient: agentens eneste vej til at røre ved et repository.

Orchestratoren taler ALDRIG direkte til filsystemet eller subprocess — den
spawner MCP-serveren som en separat proces og kommunikerer udelukkende via
MCP-protokollen (stdio-transport), ligesom Claude Code eller enhver anden
MCP-klient ville gøre. Det er det, der gør "MCP bliver faktisk brugt" sandt
frem for en påstand.
"""

from __future__ import annotations

import sys
from contextlib import AsyncExitStack
from types import TracebackType

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

from agentops.gateway.schemas import ToolDefinition
from agentops.observability.tracing import SpanType, mlflow
from agentops.security.secrets import redact_mapping


class MCPToolError(Exception):
    """Rejst når et MCP tool call returnerer en fejl (is_error=True)."""


class MCPClient:
    """Async context manager der holder én MCP-session åben for én agent-kørsel."""

    def __init__(self, workspace_root: str, *, allow_file_edits: bool = True):
        self._workspace_root = workspace_root
        self._allow_file_edits = allow_file_edits
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None

    async def __aenter__(self) -> MCPClient:
        self._stack = AsyncExitStack()
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "agentops.mcp_server"],
            env={
                "AGENT_WORKSPACE_ROOT": self._workspace_root,
                "MCP_DISABLE_FILE_EDITS": "" if self._allow_file_edits else "true",
            },
        )
        read, write = await self._stack.enter_async_context(stdio_client(params))
        session = await self._stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self._session = session
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._stack is not None:
            await self._stack.aclose()

    async def list_tool_definitions(self) -> list[ToolDefinition]:
        assert self._session is not None, "MCPClient skal bruges som 'async with'"
        result = await self._session.list_tools()
        return [
            ToolDefinition(
                name=t.name, description=t.description or "", input_schema=t.input_schema
            )
            for t in result.tools
        ]

    async def call_tool(self, name: str, arguments: dict) -> str:
        """Kalder et tool og returnerer dets tekst-content som en streng.

        Vi bruger bevidst den almindelige `content`-liste (TextContent) frem for
        `structured_content`: MCP-SDK'et populerer kun structured_content for
        visse returtyper (fx `list[dict]`), mens en almindelig `dict`-returtype
        ikke får en JSON-schema udledt og derfor mangler den. Text-content er
        altid til stede og JSON-serialiseret af vores tools, så det er den
        ensartede kontrakt, resten af platformen (deterministic provider,
        MLflow-tracing) parser imod.
        """
        assert self._session is not None, "MCPClient skal bruges som 'async with'"
        with mlflow.start_span(name=f"tool:{name}", span_type=SpanType.TOOL) as span:
            span.set_inputs(redact_mapping({"tool": name, "arguments": arguments}))
            result = await self._session.call_tool(name, arguments)
            text = _text_content(result)
            span.set_outputs({"is_error": bool(result.is_error), "content": text[:4000]})
            if result.is_error:
                raise MCPToolError(text)
            return text


def _text_content(result: types.CallToolResult) -> str:
    texts = [block.text for block in result.content if isinstance(block, types.TextContent)]
    return "\n".join(texts)
