"""Minimal, dependency-fri unified-diff applier.

Vi bruger bevidst IKKE systemets `patch`-binary: at give en agent mulighed for
at sende fritekst til en shell-kommando (`patch -pN < text`) ville genindføre
den command-injection-risiko, sikkerhedslaget ellers lukker. I stedet parser vi
et begrænset unified-diff-format i ren Python og anvender hunks linje-for-linje.

Begrænsninger (dokumenteret i docs/security.md):
- Understøtter kun én fil pr. patch.
- Ingen fuzzy matching — konteksttlinjer skal matche præcist.
- Ingen understøttelse af binære filer, filomdøbning eller nye/slettede filer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class PatchError(Exception):
    """Rejst når en unified diff ikke kan parses eller ikke matcher filindholdet."""


@dataclass(frozen=True)
class Hunk:
    old_start: int
    lines: list[tuple[str, str]]  # (' ', '+', '-') og linjeindhold uden præfiks


@dataclass(frozen=True)
class ParsedPatch:
    target_path: str
    hunks: list[Hunk]


def parse_unified_diff(diff_text: str) -> ParsedPatch:
    lines = diff_text.splitlines()
    target_path: str | None = None
    hunks: list[Hunk] = []
    current_hunk: Hunk | None = None

    for line in lines:
        if line.startswith("--- "):
            continue
        if line.startswith("+++ "):
            raw = line[4:].strip()
            raw = raw.split("\t")[0]
            if raw.startswith(("a/", "b/")):
                raw = raw[2:]
            target_path = raw
            continue
        match = _HUNK_HEADER.match(line)
        if match:
            if current_hunk is not None:
                hunks.append(current_hunk)
            current_hunk = Hunk(old_start=int(match.group(1)), lines=[])
            continue
        if current_hunk is not None:
            if line.startswith("+"):
                current_hunk.lines.append(("+", line[1:]))
            elif line.startswith("-"):
                current_hunk.lines.append(("-", line[1:]))
            elif line.startswith(" "):
                current_hunk.lines.append((" ", line[1:]))
            elif line == "":
                current_hunk.lines.append((" ", ""))

    if current_hunk is not None:
        hunks.append(current_hunk)

    if target_path is None:
        raise PatchError("Kunne ikke finde en '+++ b/<path>' header i patchen.")
    if not hunks:
        raise PatchError("Patchen indeholder ingen hunks (@@ ... @@).")

    return ParsedPatch(target_path=target_path, hunks=hunks)


def apply_patch_to_text(original_text: str, patch: ParsedPatch) -> str:
    original_lines = original_text.splitlines()
    result: list[str] = []
    cursor = 0  # 0-indexed position in original_lines already copied to result

    for hunk in patch.hunks:
        hunk_start = hunk.old_start - 1
        if hunk_start < cursor:
            raise PatchError("Hunks overlapper eller er ikke i stigende rækkefølge.")
        result.extend(original_lines[cursor:hunk_start])
        cursor = hunk_start

        for op, content in hunk.lines:
            if op == " ":
                if cursor >= len(original_lines) or original_lines[cursor] != content:
                    raise PatchError(
                        f"Kontekstlinje matcher ikke ved linje {cursor + 1}: forventede "
                        f"{content!r}, fandt {original_lines[cursor] if cursor < len(original_lines) else '<EOF>'!r}."
                    )
                result.append(content)
                cursor += 1
            elif op == "-":
                if cursor >= len(original_lines) or original_lines[cursor] != content:
                    raise PatchError(f"Linje til fjernelse matcher ikke ved linje {cursor + 1}.")
                cursor += 1
            elif op == "+":
                result.append(content)

    result.extend(original_lines[cursor:])
    trailing_newline = "\n" if original_text.endswith("\n") else ""
    return "\n".join(result) + trailing_newline
