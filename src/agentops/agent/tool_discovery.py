"""Dynamisk MCP tool discovery.

I stedet for altid at sende ALLE MCP-værktøjers beskrivelser/schemas til
modellen (mere context, flere tokens, mere "tool-støj"), vælger denne modul
en delmængde relevant for opgaven — enten fra den valgte skills
`recommended_tools` (se `agentops.agent.skills`), eller via en simpel
keyword-baseret fallback, hvis ingen skill matchede.

Bevidst FAIL-OPEN på tilgængelighed (ingen match → vis alt), i modsætning til
risk-godkendelse, som altid er fail-closed: at vise et ekstra read-only tool
for meget er ikke en sikkerhedsrisiko, men at skjule et nødvendigt tool ville
blot gøre agenten ude af stand til at løse opgaven."""

from __future__ import annotations

from agentops.agent.skills import Skill
from agentops.gateway.schemas import ToolDefinition

_ALWAYS_INCLUDE = {"get_repository_status"}
"""Billig, næsten altid nyttig orientering — udelades ikke af discovery."""

_FALLBACK_KEYWORD_TOOLS: dict[str, list[str]] = {
    "test": ["run_tests", "search_code", "read_file"],
    "database": ["search_code", "read_file", "get_git_diff"],
    "migration": ["search_code", "read_file", "get_git_diff"],
    "skema": ["search_code", "read_file", "get_git_diff"],
    "sikkerhed": ["search_code", "read_file", "get_git_diff", "get_repository_status"],
    "security": ["search_code", "read_file", "get_git_diff", "get_repository_status"],
    "api": ["search_code", "read_file", "get_project_documentation"],
    "dokumentation": ["get_project_documentation", "read_file"],
    "fejl": ["run_tests", "search_code", "read_file", "get_git_diff", "apply_patch"],
    "bug": ["run_tests", "search_code", "read_file", "get_git_diff", "apply_patch"],
}


def discover_relevant_tools(
    task_description: str, all_tools: list[ToolDefinition], skill: Skill | None
) -> list[ToolDefinition]:
    available_names = {t.name for t in all_tools}
    matched: set[str] = set()

    if skill is not None:
        matched |= set(skill.recommended_tools)
    else:
        text = task_description.lower()
        for keyword, tool_names in _FALLBACK_KEYWORD_TOOLS.items():
            if keyword in text:
                matched |= set(tool_names)

    if not matched:
        # Intet skill og intet keyword matchede — vi har ingen begrundet grund til at
        # skjule noget, så vis hele værktøjskassen (fail-open på tilgængelighed).
        return all_tools

    wanted = (matched | _ALWAYS_INCLUDE) & available_names
    return [t for t in all_tools if t.name in wanted]
