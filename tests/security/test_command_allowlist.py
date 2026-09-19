import subprocess

import pytest

from agentops.security.commands import CommandSecurityError, run_git_readonly, run_pytest


@pytest.fixture
def git_repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "file.txt").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
    return tmp_path


def test_allows_git_status(git_repo):
    result = run_git_readonly("status", cwd=git_repo)
    assert result.returncode == 0
    assert "branch" in result.stdout.lower() or "nothing to commit" in result.stdout.lower()


def test_allows_git_diff(git_repo):
    (git_repo / "file.txt").write_text("changed\n")
    result = run_git_readonly("diff", cwd=git_repo)
    assert result.returncode == 0
    assert "changed" in result.stdout


def test_rejects_unlisted_git_subcommand(git_repo):
    with pytest.raises(CommandSecurityError):
        run_git_readonly("push", cwd=git_repo)


def test_rejects_dangerous_git_flag(git_repo):
    with pytest.raises(CommandSecurityError):
        run_git_readonly("log", ["--upload-pack=/bin/sh"], cwd=git_repo)


def test_run_pytest_rejects_path_traversal(tmp_path):
    with pytest.raises(CommandSecurityError):
        run_pytest("../../etc", cwd=tmp_path)


def test_run_pytest_rejects_absolute_path(tmp_path):
    with pytest.raises(CommandSecurityError):
        run_pytest("/etc/passwd", cwd=tmp_path)


def test_run_pytest_executes_within_cwd(tmp_path):
    test_file = tmp_path / "test_sample.py"
    test_file.write_text("def test_ok():\n    assert 1 == 1\n")
    result = run_pytest("test_sample.py", cwd=tmp_path)
    assert result.returncode == 0
    assert "1 passed" in result.stdout
