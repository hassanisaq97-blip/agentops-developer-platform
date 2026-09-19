"""MCP-server der eksponerer developer-tools for coding-agenten.

Bygget på den officielle `mcp` Python SDK (v2.x, `mcp.server.mcpserver.MCPServer`
— efterfølgeren til v1's `FastMCP`, se migrationsnoten i README for MCP-serveren).

Serveren kender kun til ét repository ad gangen (`workspace_root`) og kan ikke
læse eller skrive uden for det, jf. `agentops.security.workspace.WorkspaceSandbox`.
`allow_file_edits=False` fjerner `edit_file`/`apply_patch` helt fra
tool-listen — en read-only MCP-server har ingen kodesti, der kan skrive.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from mcp import types
from mcp.server.mcpserver import MCPServer

from agentops.mcp_server import tools
from agentops.security.commands import CommandSecurityError
from agentops.security.exceptions import PathSecurityError
from agentops.security.workspace import WorkspaceSandbox

READ_ONLY = types.ToolAnnotations(
    read_only_hint=True, destructive_hint=False, open_world_hint=False
)
DESTRUCTIVE = types.ToolAnnotations(
    read_only_hint=False, destructive_hint=True, open_world_hint=False
)


def build_server(workspace_root: Path, *, allow_file_edits: bool = True) -> MCPServer:
    sandbox = WorkspaceSandbox(root=workspace_root)
    server = MCPServer(
        name="agentops-developer-tools",
        version="0.1.0",
        instructions=(
            "Developer tools til AgentOps Developer Platform. Alle stier er relative til "
            "repository-workspacet. Brug search_code/read_file/list_repository til at "
            "orientere dig, før du foreslår ændringer."
        ),
    )

    @server.tool(annotations=READ_ONLY, description="Søg efter en tekststreng i kodebasen.")
    def search_code(query: str, glob: str = "**/*", max_results: int = 50) -> list[dict]:
        try:
            return [asdict(m) for m in tools.search_code(sandbox, query, glob, max_results)]
        except (PathSecurityError, ValueError) as exc:
            return [{"error": str(exc)}]

    @server.tool(
        annotations=READ_ONLY, description="Læs indholdet af en fil (evt. et linjeinterval)."
    )
    def read_file(path: str, start_line: int | None = None, end_line: int | None = None) -> str:
        try:
            return tools.read_file(sandbox, path, start_line, end_line)
        except PathSecurityError as exc:
            return f"FEJL: {exc}"

    @server.tool(annotations=READ_ONLY, description="List filer og mapper i repositoryet.")
    def list_repository(path: str = ".", max_depth: int = 3) -> list[dict]:
        try:
            return [asdict(e) for e in tools.list_repository(sandbox, path, max_depth)]
        except PathSecurityError as exc:
            return [{"error": str(exc)}]

    @server.tool(annotations=READ_ONLY, description="Vis git diff for uncommittede ændringer.")
    def get_git_diff(staged: bool = False) -> str:
        try:
            return tools.get_git_diff(sandbox, staged)
        except CommandSecurityError as exc:
            return f"FEJL: {exc}"

    @server.tool(annotations=READ_ONLY, description="Vis git branch/status og seneste commit.")
    def get_repository_status() -> dict:
        try:
            return tools.get_repository_status(sandbox)
        except CommandSecurityError as exc:
            return {"error": str(exc)}

    @server.tool(
        annotations=READ_ONLY,
        description="Søg i projektdokumentation (README.md, CLAUDE.md, docs/**/*.md).",
    )
    def get_project_documentation(query: str | None = None) -> list[dict]:
        return tools.get_project_documentation(sandbox, query)

    @server.tool(
        annotations=types.ToolAnnotations(
            read_only_hint=False, destructive_hint=False, open_world_hint=False
        ),
        description="Kør pytest og returnér et struktureret resultat (pass/fail-antal).",
    )
    def run_tests(test_target: str | None = None) -> dict:
        try:
            result = tools.run_tests(sandbox, test_target)
            return asdict(result)
        except (PathSecurityError, CommandSecurityError) as exc:
            return {"error": str(exc)}

    if allow_file_edits:

        @server.tool(
            annotations=DESTRUCTIVE,
            description="HIGH RISK: overskriv en fils fulde indhold. Kræver godkendelse i orchestratoren.",
        )
        def edit_file(path: str, content: str) -> dict:
            try:
                return tools.edit_file(sandbox, path, content)
            except PathSecurityError as exc:
                return {"error": str(exc)}

        @server.tool(
            annotations=DESTRUCTIVE,
            description="HIGH RISK: anvend en unified diff på én fil. Kræver godkendelse i orchestratoren.",
        )
        def apply_patch(diff_text: str) -> dict:
            try:
                return tools.apply_patch(sandbox, diff_text)
            except PathSecurityError as exc:
                return {"error": str(exc)}

    return server
