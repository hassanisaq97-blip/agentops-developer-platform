"""Context engineering: eksplicitte strategier for hvad agenten ser, før den starter.

Context er en begrænset ressource — både i tokens og i risiko (mere ukontrolleret
tekst i prompten er mere overflade for prompt injection). Disse fire strategier
gør det muligt at måle den faktiske effekt af forskellige context-tilgange i
stedet for blot at hævde, at "mere context er bedre" eller "MCP hjælper".

STRATEGI A (MINIMAL):     kun opgaveteksten. Ingen instruktioner, ingen tools.
STRATEGI B (CLAUDE_MD):   + CLAUDE.md's indhold i system-prompten. Stadig ingen tools.
STRATEGI C (TARGETED_MCP): CLAUDE.md + fuld MCP-værktøjskasse. Agenten skal selv
                           opdage repository-strukturen via tool calls.
STRATEGI D (OPTIMIZED):   som C, men et forudberegnet repository-resumé
                           (fil-træ + dokumentationsuddrag) indsættes i
                           system-prompten, så agenten ikke behøver bruge de
                           første tool calls på ren orientering.

Se docs/experiments/ for de faktiske, reproducerbare målinger af disse fire
strategier og en ærlig diskussion af, hvad der kunne og ikke kunne måles med
den deterministiske test-provider.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

_BASE_INSTRUCTIONS = (
    "Du er en coding agent i AgentOps Developer Platform. Du får en softwareudviklingsopgave "
    "og skal løse den ved at bruge de tools, du har adgang til, til at undersøge repositoryet, "
    "før du foreslår eller foretager ændringer. Forklar kort din begrundelse ved hvert tool-kald."
)

CLAUDE_MD_FILENAME = "CLAUDE.md"


class ContextStrategy(StrEnum):
    MINIMAL = "minimal"
    CLAUDE_MD = "claude_md"
    TARGETED_MCP = "targeted_mcp"
    OPTIMIZED = "optimized"


STRATEGIES_WITH_TOOLS = {ContextStrategy.TARGETED_MCP, ContextStrategy.OPTIMIZED}


def build_system_prompt(strategy: ContextStrategy, workspace_root: Path, task: str) -> str:
    if strategy == ContextStrategy.MINIMAL:
        return f"Opgave: {task}"

    claude_md = _read_claude_md(workspace_root)

    if strategy == ContextStrategy.CLAUDE_MD:
        return f"{_BASE_INSTRUCTIONS}\n\n--- CLAUDE.md ---\n{claude_md}"

    if strategy == ContextStrategy.TARGETED_MCP:
        return f"{_BASE_INSTRUCTIONS}\n\n--- CLAUDE.md ---\n{claude_md}"

    if strategy == ContextStrategy.OPTIMIZED:
        summary = _build_repository_summary(workspace_root)
        return (
            f"{_BASE_INSTRUCTIONS}\n\n--- CLAUDE.md ---\n{claude_md}\n\n"
            f"--- Repository-resumé (forudberegnet, spar dine første tool calls) ---\n{summary}"
        )

    raise ValueError(f"Ukendt context-strategi: {strategy}")


def _read_claude_md(workspace_root: Path) -> str:
    claude_md_path = workspace_root / CLAUDE_MD_FILENAME
    if claude_md_path.is_file():
        return claude_md_path.read_text(encoding="utf-8", errors="ignore")
    return "(Intet CLAUDE.md fundet i dette repository.)"


def _build_repository_summary(workspace_root: Path, max_entries: int = 40) -> str:
    from agentops.security.workspace import DENYLISTED_DIR_NAMES

    entries = []
    for path in sorted(workspace_root.rglob("*")):
        relative = path.relative_to(workspace_root)
        if any(part in DENYLISTED_DIR_NAMES for part in relative.parts):
            continue
        entries.append(str(relative))
        if len(entries) >= max_entries:
            break

    readme_path = workspace_root / "README.md"
    readme_excerpt = (
        readme_path.read_text(encoding="utf-8", errors="ignore")[:400]
        if readme_path.is_file()
        else ""
    )

    tree_text = "\n".join(entries)
    return f"Filtræ:\n{tree_text}\n\nREADME-uddrag:\n{readme_excerpt}"
