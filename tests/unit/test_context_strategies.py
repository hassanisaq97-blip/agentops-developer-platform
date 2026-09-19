from agentops.agent.context import ContextStrategy, build_system_prompt


def _make_repo(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("Dette repository bruger pytest og har en src/-mappe.\n")
    (tmp_path / "README.md").write_text("# Demo\n\nEn lille regnemaskine til test af agenten.\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x = 1\n")
    return tmp_path


def test_minimal_strategy_contains_only_the_task(tmp_path):
    repo = _make_repo(tmp_path)
    prompt = build_system_prompt(ContextStrategy.MINIMAL, repo, "Ret fejlen")
    assert prompt == "Opgave: Ret fejlen"
    assert "CLAUDE.md" not in prompt


def test_claude_md_strategy_includes_claude_md_content(tmp_path):
    repo = _make_repo(tmp_path)
    prompt = build_system_prompt(ContextStrategy.CLAUDE_MD, repo, "Ret fejlen")
    assert "bruger pytest" in prompt
    assert (
        "Ret fejlen" not in prompt
    )  # opgaveteksten sendes separat som user-besked, ikke i system-prompten


def test_claude_md_strategy_handles_missing_claude_md(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    prompt = build_system_prompt(ContextStrategy.CLAUDE_MD, tmp_path, "Ret fejlen")
    assert "Intet CLAUDE.md fundet" in prompt


def test_targeted_mcp_strategy_matches_claude_md_strategy_content(tmp_path):
    repo = _make_repo(tmp_path)
    claude_md_prompt = build_system_prompt(ContextStrategy.CLAUDE_MD, repo, "Ret fejlen")
    targeted_prompt = build_system_prompt(ContextStrategy.TARGETED_MCP, repo, "Ret fejlen")
    assert (
        claude_md_prompt == targeted_prompt
    )  # forskellen mellem C og B er tool-adgang, ikke prompten


def test_optimized_strategy_adds_repository_summary_on_top_of_claude_md(tmp_path):
    repo = _make_repo(tmp_path)
    claude_md_prompt = build_system_prompt(ContextStrategy.CLAUDE_MD, repo, "Ret fejlen")
    optimized_prompt = build_system_prompt(ContextStrategy.OPTIMIZED, repo, "Ret fejlen")

    assert optimized_prompt.startswith(claude_md_prompt)
    assert "Repository-resumé" in optimized_prompt
    assert "src/app.py" in optimized_prompt
    assert "regnemaskine" in optimized_prompt  # fra README-uddraget


def test_optimized_strategy_produces_a_larger_prompt_than_targeted_mcp(tmp_path):
    """Den optimerede strategi bruger flere tokens i system-prompten for at spare tool calls —
    en reel, målbar afvejning, ikke en påstand om at 'mere er bedre'."""
    repo = _make_repo(tmp_path)
    targeted = build_system_prompt(ContextStrategy.TARGETED_MCP, repo, "Ret fejlen")
    optimized = build_system_prompt(ContextStrategy.OPTIMIZED, repo, "Ret fejlen")
    assert len(optimized) > len(targeted)
