"""Klargøring af eval-fixture-repositories til en agent-kørsel.

Fixtures ligger som almindelige filer under `evals/fixtures/<case>/` (ikke som
nestede git-repos i selve platform-repositoryet). Før en evaluering kopierer
vi fixturen til en midlertidig mappe og initialiserer et rigtigt git-repo der
— det er den samme fremgangsmåde som demoen i `scripts/run_demo.py` bruger,
så agentens MCP-tools (get_git_diff, get_repository_status) har noget reelt
at arbejde med.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

FIXTURES_ROOT = Path(__file__).resolve().parents[3] / "evals" / "fixtures"


def fixture_path(name: str) -> Path:
    path = FIXTURES_ROOT / name
    if not path.is_dir():
        raise FileNotFoundError(f"Eval-fixture '{name}' findes ikke under {FIXTURES_ROOT}.")
    return path


def prepare_workspace(fixture_name: str, destination: Path) -> Path:
    """Kopierer en fixture til `destination` og initialiserer et git-repo. Returnerer stien."""
    source = fixture_path(fixture_name)
    shutil.copytree(source, destination, dirs_exist_ok=True)

    subprocess.run(["git", "init", "-q"], cwd=destination, check=True)
    subprocess.run(
        ["git", "config", "user.email", "eval@agentops.local"], cwd=destination, check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "AgentOps Eval Runner"], cwd=destination, check=True
    )
    subprocess.run(["git", "add", "."], cwd=destination, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "initial fixture state"], cwd=destination, check=True
    )

    return destination
