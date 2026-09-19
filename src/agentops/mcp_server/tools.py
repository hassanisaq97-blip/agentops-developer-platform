"""Ren funktionsimplementering af MCP developer-tools.

Disse funktioner er bevidst adskilt fra MCP-registreringen i `server.py`, så
de kan unit-testes direkte uden en kørende MCP-session, og så risk-metadata i
`agentops.agent.risk` kan referere til de samme tool-navne uden en cirkulær
afhængighed til MCP-SDK'et.

Alle funktioner tager en `WorkspaceSandbox` og opererer udelukkende gennem den —
ingen direkte `open()`/`Path` filsystemadgang uden om sandboxen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from agentops.mcp_server.patching import PatchError, apply_patch_to_text, parse_unified_diff
from agentops.security.commands import run_git_readonly, run_pytest
from agentops.security.exceptions import PathSecurityError
from agentops.security.workspace import DENYLISTED_DIR_NAMES, WorkspaceSandbox

MAX_SEARCH_RESULTS = 50
MAX_LISTED_ENTRIES = 500
MAX_FILE_SEARCH_BYTES = 512_000
DOC_FILE_PATTERNS = ("README.md", "CLAUDE.md", "docs/**/*.md")


@dataclass
class SearchMatch:
    path: str
    line_number: int
    line: str


@dataclass
class RepositoryEntry:
    path: str
    is_dir: bool


@dataclass
class TestRunResult:
    returncode: int
    passed: int | None
    failed: int | None
    summary: str
    stdout: str
    stderr: str
    timed_out: bool = False


_PASSED_PATTERN = re.compile(r"(\d+) passed")
_FAILED_PATTERN = re.compile(r"(\d+) failed")


def search_code(
    sandbox: WorkspaceSandbox, query: str, glob: str = "**/*", max_results: int = MAX_SEARCH_RESULTS
) -> list[SearchMatch]:
    """Søger efter en literal delstreng i tekstfiler under workspacet."""
    if not query.strip():
        raise ValueError("query må ikke være tom.")

    matches: list[SearchMatch] = []
    for path in sorted(sandbox.root.glob(glob)):
        if any(part in DENYLISTED_DIR_NAMES for part in path.relative_to(sandbox.root).parts):
            continue
        if not path.is_file():
            continue
        try:
            if path.stat().st_size > MAX_FILE_SEARCH_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
        except (UnicodeDecodeError, OSError):
            continue

        for line_number, line in enumerate(text.splitlines(), start=1):
            if query in line:
                matches.append(
                    SearchMatch(
                        path=sandbox.to_relative(path), line_number=line_number, line=line.strip()
                    )
                )
                if len(matches) >= max_results:
                    return matches
    return matches


def read_file(
    sandbox: WorkspaceSandbox,
    path: str,
    start_line: int | None = None,
    end_line: int | None = None,
) -> str:
    content = sandbox.read_text(path)
    if start_line is None and end_line is None:
        return content
    lines = content.splitlines()
    start = max((start_line or 1) - 1, 0)
    end = end_line if end_line is not None else len(lines)
    return "\n".join(lines[start:end])


def list_repository(
    sandbox: WorkspaceSandbox, path: str = ".", max_depth: int = 3
) -> list[RepositoryEntry]:
    root = sandbox.resolve(path) if path != "." else sandbox.root
    entries: list[RepositoryEntry] = []
    for item in sorted(root.rglob("*")):
        relative = item.relative_to(sandbox.root)
        if any(part in DENYLISTED_DIR_NAMES for part in relative.parts):
            continue
        if len(relative.parts) > max_depth:
            continue
        entries.append(RepositoryEntry(path=str(relative), is_dir=item.is_dir()))
        if len(entries) >= MAX_LISTED_ENTRIES:
            break
    return entries


def get_git_diff(sandbox: WorkspaceSandbox, staged: bool = False) -> str:
    args = ["--staged"] if staged else []
    result = run_git_readonly("diff", args, cwd=sandbox.root)
    return result.stdout or "(ingen ændringer)"


def get_repository_status(sandbox: WorkspaceSandbox) -> dict:
    status = run_git_readonly("status", ["--short", "--branch"], cwd=sandbox.root)
    head = run_git_readonly("log", ["-1", "--oneline"], cwd=sandbox.root)
    return {
        "branch_and_changes": status.stdout.strip(),
        "head_commit": head.stdout.strip() or "(ingen commits endnu)",
    }


def get_project_documentation(sandbox: WorkspaceSandbox, query: str | None = None) -> list[dict]:
    doc_files: list[Path] = []
    for pattern in DOC_FILE_PATTERNS:
        doc_files.extend(sandbox.root.glob(pattern))

    results = []
    for doc_path in sorted(set(doc_files)):
        if not doc_path.is_file():
            continue
        text = doc_path.read_text(encoding="utf-8", errors="ignore")
        if query and query.lower() not in text.lower():
            continue
        excerpt = text[:1000]
        results.append({"path": sandbox.to_relative(doc_path), "excerpt": excerpt})
    return results


def run_tests(
    sandbox: WorkspaceSandbox, test_target: str | None = None, timeout: float = 60.0
) -> TestRunResult:
    if test_target:
        sandbox.resolve(test_target)  # validerer at target er inden for workspacet
    result = run_pytest(test_target, cwd=sandbox.root, timeout=timeout)
    output = result.stdout + "\n" + result.stderr
    passed_match = _PASSED_PATTERN.search(output)
    failed_match = _FAILED_PATTERN.search(output)
    ran_normally = result.returncode in {0, 1} and (passed_match or failed_match)
    # pytest's summary line omits a category when its count is zero (e.g. "1 passed"
    # implies 0 failed) — so we default the omitted side to 0 rather than None, but
    # only when we know a normal test run actually happened (not e.g. a collection error).
    passed = int(passed_match.group(1)) if passed_match else (0 if ran_normally else None)
    failed = int(failed_match.group(1)) if failed_match else (0 if ran_normally else None)
    summary_lines = [
        line
        for line in output.splitlines()
        if "passed" in line or "failed" in line or "error" in line
    ]
    summary = summary_lines[-1].strip() if summary_lines else output.strip()[-200:]
    return TestRunResult(
        returncode=result.returncode,
        passed=passed,
        failed=failed,
        summary=summary,
        stdout=result.stdout,
        stderr=result.stderr,
        timed_out=result.timed_out,
    )


def edit_file(sandbox: WorkspaceSandbox, path: str, content: str) -> dict:
    """HIGH RISK: overskriver en fil i workspacet. Skal gates af approval-laget i orchestratoren."""
    try:
        old_content = sandbox.read_text(path)
    except PathSecurityError:
        old_content = ""
    resolved = sandbox.write_text(path, content)
    return {
        "path": sandbox.to_relative(resolved),
        "bytes_written": len(content.encode("utf-8")),
        "previous_size_bytes": len(old_content.encode("utf-8")),
    }


def apply_patch(sandbox: WorkspaceSandbox, diff_text: str) -> dict:
    """HIGH RISK: anvender en unified diff på én fil i workspacet."""
    try:
        parsed = parse_unified_diff(diff_text)
        target_path = sandbox.resolve(parsed.target_path)
        original = sandbox.read_text(parsed.target_path)
        patched = apply_patch_to_text(original, parsed)
    except PatchError as exc:
        return {"applied": False, "error": str(exc)}
    target_path.write_text(patched, encoding="utf-8")
    return {
        "applied": True,
        "path": parsed.target_path,
        "bytes_written": len(patched.encode("utf-8")),
    }
