"""Risikoklassificering af agent-handlinger (MCP tool calls).

Dette er den centrale politik for human-in-the-loop: hvor meget kan agenten
gøre autonomt, og hvornår kræves eksplicit menneskelig godkendelse?

LAV:    read-only inspektion — søgning, læsning, git status/diff, dokumentation
MIDDEL: kører kode, men ændrer ikke workspacet permanent (tests)
HØJ:    ændrer filer i workspacet — irreversibelt uden en separat git-operation
"""

from __future__ import annotations

from enum import StrEnum


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


TOOL_RISK_LEVELS: dict[str, RiskLevel] = {
    "search_code": RiskLevel.LOW,
    "read_file": RiskLevel.LOW,
    "list_repository": RiskLevel.LOW,
    "get_git_diff": RiskLevel.LOW,
    "get_project_documentation": RiskLevel.LOW,
    "get_repository_status": RiskLevel.LOW,
    "run_tests": RiskLevel.MEDIUM,
    "edit_file": RiskLevel.HIGH,
    "apply_patch": RiskLevel.HIGH,
}


def risk_level_for(tool_name: str) -> RiskLevel:
    """Ukendte tools behandles som HIGH risk — fail closed, ikke fail open."""
    return TOOL_RISK_LEVELS.get(tool_name, RiskLevel.HIGH)


def requires_approval(tool_name: str, *, auto_approve_high_risk: bool) -> bool:
    level = risk_level_for(tool_name)
    if level == RiskLevel.LOW:
        return False
    if level == RiskLevel.MEDIUM:
        return False
    return not auto_approve_high_risk
