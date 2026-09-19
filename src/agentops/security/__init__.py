"""Sikkerhedslag: repository-sandboxing, command allowlisting og secret-redaction.

Dette modul er trust-boundary'en mellem coding-agenten og det underliggende
filsystem/OS. Alle MCP developer tools skal gå igennem `WorkspaceSandbox` og
`run_git_readonly`/`run_pytest` — aldrig direkte `open()` eller `subprocess` med
shell=True eller ukontrollerede argumenter.
"""

from agentops.security.commands import (
    CommandResult,
    CommandSecurityError,
    run_git_readonly,
    run_pytest,
)
from agentops.security.exceptions import PathSecurityError
from agentops.security.secrets import redact_mapping, redact_text
from agentops.security.workspace import WorkspaceSandbox

__all__ = [
    "CommandResult",
    "CommandSecurityError",
    "PathSecurityError",
    "WorkspaceSandbox",
    "redact_mapping",
    "redact_text",
    "run_git_readonly",
    "run_pytest",
]
