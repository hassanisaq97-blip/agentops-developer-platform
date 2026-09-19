"""Entrypoint: `python -m agentops.mcp_server`.

Starter MCP-serveren over stdio-transport, som forventet af Claude Code og
andre MCP-klienter. Workspace-roden og skriverettigheder styres af
environment variables (se .env.example).
"""

from __future__ import annotations

from agentops.mcp_server.server import build_server
from agentops.settings import get_settings


def main() -> None:
    settings = get_settings()
    server = build_server(
        settings.workspace_root,
        allow_file_edits=not _env_flag_disabled(),
    )
    server.run(transport="stdio")


def _env_flag_disabled() -> bool:
    import os

    return os.environ.get("MCP_DISABLE_FILE_EDITS", "").lower() in {"1", "true", "yes"}


if __name__ == "__main__":
    main()
