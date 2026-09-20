#!/usr/bin/env python3
"""Klargør en git-initialiseret arbejdskopi af `demo_repo/` til direkte MCP-brug.

Formål: `.mcp.json` i roden af dette repository peger MCP-serveren på
`.mcp_demo_workspace/` (ikke direkte på `demo_repo/`), så en klient som
Claude Code kan forbinde til MCP-serveren og med det samme bruge
`get_repository_status`/`get_git_diff`, som begge kræver et rigtigt
git-repository. `demo_repo/` selv holdes bevidst UDEN sit eget `.git` i
platform-repositoryet — et indlejret git-repo i et git-repo giver
"gitlink"-forvirring (samme grund som `scripts/run_demo.py` og
`agentops.evaluation.fixtures` altid kopierer fixtures til en midlertidig
mappe, før de git-initialiserer dem).

`.mcp_demo_workspace/` er git-ignoreret og må frit slettes/genskabes — kør
dette script igen for at nulstille den til demo_repo's oprindelige (buggy)
tilstand, fx efter Claude Code har rettet buggen og du vil demonstrere det
igen.

Brug: `python scripts/prepare_mcp_demo_workspace.py`
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / "demo_repo"
DESTINATION = REPO_ROOT / ".mcp_demo_workspace"


def main() -> None:
    if DESTINATION.exists():
        shutil.rmtree(DESTINATION)
    shutil.copytree(SOURCE, DESTINATION)

    for cmd in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "mcp-demo@agentops.local"],
        ["git", "config", "user.name", "AgentOps MCP Demo"],
        ["git", "add", "."],
        ["git", "commit", "-q", "-m", "initial demo workspace state (indeholder en kendt bug)"],
    ):
        subprocess.run(cmd, cwd=DESTINATION, check=True)

    print(f"Klargjort: {DESTINATION}")
    print("Genstart/åbn Claude Code i denne mappe (eller kør `claude mcp list` for at bekræfte),")
    print("så det checkede ind '.mcp.json' forbinder til MCP-serveren med denne workspace.")


if __name__ == "__main__":
    main()
