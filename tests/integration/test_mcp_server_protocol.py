"""Integrationstest: forbinder som en RIGTIG MCP-klient til MCP-serveren over stdio.

Dette er bevidst forskelligt fra tests/unit/test_mcp_tools.py, som kalder
tool-funktionerne direkte. Her spawner vi den faktiske server-proces
(`python -m agentops.mcp_server`) og taler MCP-protokollen til den via den
officielle SDK's ClientSession, for at bevise at MCP rent faktisk bliver brugt
— ikke kun at tool-logikken tilfældigvis findes et sted i kodebasen.
"""

from __future__ import annotations

import subprocess
import sys

import pytest
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client


@pytest.fixture
def demo_workspace(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "calculator.py").write_text("def add(a, b):\n    return a - b\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    return tmp_path


@pytest.mark.integration
async def test_list_tools_over_real_mcp_session(demo_workspace):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "agentops.mcp_server"],
        env={"AGENT_WORKSPACE_ROOT": str(demo_workspace)},
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        result = await session.list_tools()

    tool_names = {tool.name for tool in result.tools}
    assert "search_code" in tool_names
    assert "read_file" in tool_names
    assert "run_tests" in tool_names
    assert "edit_file" in tool_names


@pytest.mark.integration
async def test_call_search_code_over_real_mcp_session(demo_workspace):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "agentops.mcp_server"],
        env={"AGENT_WORKSPACE_ROOT": str(demo_workspace)},
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool("search_code", {"query": "def add"})

    assert isinstance(result, types.CallToolResult)
    assert result.is_error is not True
    assert result.structured_content is not None
