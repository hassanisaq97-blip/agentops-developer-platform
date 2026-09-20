from agentops.agent.skills import SKILLS
from agentops.agent.tool_discovery import discover_relevant_tools
from agentops.gateway.schemas import ToolDefinition

_ALL_TOOLS = [
    ToolDefinition(name=n, description=n)
    for n in (
        "search_code",
        "read_file",
        "list_repository",
        "get_git_diff",
        "get_project_documentation",
        "get_repository_status",
        "run_tests",
        "edit_file",
        "apply_patch",
    )
]


def _skill(name: str):
    return next(s for s in SKILLS if s.name == name)


def test_discovery_with_skill_returns_subset_of_recommended_tools():
    skill = _skill("security_review")
    discovered = discover_relevant_tools("Lav en security review.", _ALL_TOOLS, skill)
    names = {t.name for t in discovered}
    assert names <= set(skill.recommended_tools) | {"get_repository_status"}
    assert len(discovered) < len(_ALL_TOOLS)
    # En security review har ikke brug for at overskrive filer.
    assert "apply_patch" not in names
    assert "edit_file" not in names


def test_discovery_without_skill_uses_keyword_fallback():
    discovered = discover_relevant_tools(
        "Vi har et databaseproblem med et skema.", _ALL_TOOLS, None
    )
    names = {t.name for t in discovered}
    assert "search_code" in names
    assert "read_file" in names
    assert len(discovered) < len(_ALL_TOOLS)


def test_discovery_falls_back_to_all_tools_when_nothing_matches():
    discovered = discover_relevant_tools("xyzzy plugh qux", _ALL_TOOLS, None)
    assert len(discovered) == len(_ALL_TOOLS)


def test_discovery_always_includes_repository_status():
    skill = _skill("test_generation")
    discovered = discover_relevant_tools("Skriv tests.", _ALL_TOOLS, skill)
    assert any(t.name == "get_repository_status" for t in discovered)


def test_discovery_never_invents_tools_not_in_all_tools():
    limited_tools = [t for t in _ALL_TOOLS if t.name in {"search_code", "read_file"}]
    skill = _skill("debugging")
    discovered = discover_relevant_tools("Der er en bug.", limited_tools, skill)
    assert {t.name for t in discovered} <= {"search_code", "read_file"}
