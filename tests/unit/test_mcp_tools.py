import subprocess

import pytest

from agentops.mcp_server import tools
from agentops.security.exceptions import PathSecurityError
from agentops.security.workspace import WorkspaceSandbox


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "calculator.py").write_text(
        "def add(a, b):\n    return a - b\n\n\ndef subtract(a, b):\n    return a - b\n"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_calculator.py").write_text(
        "import sys\nfrom pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))\n"
        "from calculator import add\n\n"
        "def test_add():\n    assert add(2, 3) == 5\n"
    )
    (tmp_path / "README.md").write_text("# Demo\n\nEn lille regnemaskine.\n")

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)

    return WorkspaceSandbox(root=tmp_path)


def test_search_code_finds_function_definition(repo):
    matches = tools.search_code(repo, "def add")
    assert len(matches) == 1
    assert matches[0].path == "src/calculator.py"


def test_search_code_respects_glob(repo):
    matches = tools.search_code(repo, "def ", glob="tests/**/*.py")
    assert all(m.path.startswith("tests/") for m in matches)


def test_read_file_returns_full_content(repo):
    content = tools.read_file(repo, "src/calculator.py")
    assert "def add" in content


def test_read_file_returns_line_range(repo):
    content = tools.read_file(repo, "src/calculator.py", start_line=1, end_line=2)
    assert content == "def add(a, b):\n    return a - b"


def test_read_file_rejects_traversal(repo):
    with pytest.raises(PathSecurityError):
        tools.read_file(repo, "../outside.py")


def test_list_repository_excludes_git_dir(repo):
    entries = tools.list_repository(repo)
    paths = {e.path for e in entries}
    assert not any(p.startswith(".git") for p in paths)
    assert "src/calculator.py" in paths


def test_get_repository_status_reports_branch(repo):
    status = tools.get_repository_status(repo)
    assert "head_commit" in status
    assert "init" in status["head_commit"]


def test_get_git_diff_shows_uncommitted_change(repo):
    (repo.root / "src" / "calculator.py").write_text("def add(a, b):\n    return a + b\n")
    diff = tools.get_git_diff(repo)
    assert "calculator.py" in diff


def test_get_project_documentation_finds_readme(repo):
    docs = tools.get_project_documentation(repo)
    assert any(d["path"] == "README.md" for d in docs)


def test_get_project_documentation_filters_by_query(repo):
    docs = tools.get_project_documentation(repo, query="regnemaskine")
    assert len(docs) == 1
    docs_none = tools.get_project_documentation(repo, query="nonexistent-term")
    assert docs_none == []


def test_run_tests_reports_the_pre_existing_bug(repo):
    result = tools.run_tests(repo)
    assert result.returncode != 0
    assert result.failed == 1


def test_run_tests_passes_after_fix(repo):
    (repo.root / "src" / "calculator.py").write_text("def add(a, b):\n    return a + b\n")
    result = tools.run_tests(repo)
    assert result.returncode == 0
    assert result.passed == 1


def test_edit_file_writes_within_workspace(repo):
    result = tools.edit_file(repo, "src/calculator.py", "def add(a, b):\n    return a + b\n")
    assert result["path"] == "src/calculator.py"
    assert (repo.root / "src" / "calculator.py").read_text() == "def add(a, b):\n    return a + b\n"


def test_edit_file_rejects_escape(repo):
    with pytest.raises(PathSecurityError):
        tools.edit_file(repo, "../escape.py", "x = 1\n")


def test_apply_patch_fixes_bug_end_to_end(repo):
    diff = (
        "--- a/src/calculator.py\n"
        "+++ b/src/calculator.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def add(a, b):\n"
        "-    return a - b\n"
        "+    return a + b\n"
    )
    result = tools.apply_patch(repo, diff)
    assert result["applied"] is True
    test_result = tools.run_tests(repo)
    assert test_result.returncode == 0


def test_apply_patch_reports_error_on_mismatch(repo):
    diff = (
        "--- a/src/calculator.py\n"
        "+++ b/src/calculator.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def add(a, b):\n"
        "-    return WRONG_CONTEXT\n"
        "+    return a + b\n"
    )
    result = tools.apply_patch(repo, diff)
    assert result["applied"] is False
    assert "error" in result
