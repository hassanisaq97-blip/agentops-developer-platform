"""Allowlist-baseret command execution.

Trussel: hvis agenten kunne udføre vilkårlige shell-kommandoer (fx via
`subprocess.run(user_string, shell=True)`), ville en kompromitteret prompt eller
et ondsindet repository kunne opnå remote code execution. Derfor:

- Der findes ingen generisk "kør denne shell-kommando"-funktion noget sted i
  kodebasen. Kun to smalle, formålsspecifikke funktioner findes: git read-only
  inspektion og pytest-eksekvering.
- Alt kaldes med en argv-liste og `shell=False` — brugerinput bliver aldrig
  fortolket som shell-syntaks.
- Subprocess-miljøet er reduceret til PATH, så secrets i procesmiljøet
  (API-nøgler, database-URL) ikke automatisk arves af børneprocesser.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from agentops.security.exceptions import CommandSecurityError

# git-subcommands der er read-only og derfor sikre at eksponere til agenten.
ALLOWED_GIT_SUBCOMMANDS: set[str] = {"status", "diff", "log", "branch", "show"}

DEFAULT_TIMEOUT_SECONDS = 30.0

_SUBPROCESS_ENV = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")}


@dataclass(frozen=True)
class CommandResult:
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


def _run(argv: list[str], *, cwd: Path, timeout: float) -> CommandResult:
    try:
        completed = subprocess.run(  # noqa: S603 — argv er allowlisted og shell=False
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            env=_SUBPROCESS_ENV,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        return CommandResult(
            argv=argv,
            returncode=-1,
            stdout=stdout,
            stderr=f"Kommandoen overskred timeout på {timeout}s.",
            timed_out=True,
        )
    return CommandResult(
        argv=argv, returncode=completed.returncode, stdout=completed.stdout, stderr=completed.stderr
    )


def run_git_readonly(
    subcommand: str,
    extra_args: list[str] | None = None,
    *,
    cwd: Path,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> CommandResult:
    """Kører en read-only git-subcommand. Rejser CommandSecurityError for alt andet."""
    if subcommand not in ALLOWED_GIT_SUBCOMMANDS:
        raise CommandSecurityError(
            f"git-subcommand '{subcommand}' er ikke tilladt. Tilladt: {sorted(ALLOWED_GIT_SUBCOMMANDS)}"
        )
    argv = ["git", subcommand, *(extra_args or [])]
    for arg in argv:
        if (
            arg.startswith("--upload-pack")
            or arg.startswith("--receive-pack")
            or arg in {"-c", "--exec"}
        ):
            raise CommandSecurityError(f"Flaget '{arg}' er ikke tilladt.")
    return _run(argv, cwd=cwd, timeout=timeout)


def run_pytest(
    test_target: str | None,
    *,
    cwd: Path,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> CommandResult:
    """Kører pytest via `sys.executable -m pytest` inden for `cwd`.

    `test_target` skal enten være None (kør hele suiten) eller en relativ sti
    uden `..`-komponenter — valideres af kaldende MCP-tool via WorkspaceSandbox
    før dette kaldes, så vi validerer defensivt igen her.
    """
    argv = [sys.executable, "-m", "pytest", "-q", "--no-header"]
    if test_target:
        if ".." in Path(test_target).parts or Path(test_target).is_absolute():
            raise CommandSecurityError("test_target må ikke indeholde '..' eller være absolut.")
        argv.append(test_target)
    return _run(argv, cwd=cwd, timeout=timeout)
