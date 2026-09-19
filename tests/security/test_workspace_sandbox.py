import pytest

from agentops.security.exceptions import PathSecurityError
from agentops.security.workspace import WorkspaceSandbox


@pytest.fixture
def sandbox(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hello')\n")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("[core]\n")
    outside = tmp_path.parent / "outside_secret.txt"
    outside.write_text("top secret")
    return WorkspaceSandbox(root=tmp_path)


def test_resolves_valid_relative_path(sandbox, tmp_path):
    resolved = sandbox.resolve("src/app.py")
    assert resolved == (tmp_path / "src" / "app.py").resolve()


def test_rejects_dotdot_traversal(sandbox):
    with pytest.raises(PathSecurityError):
        sandbox.resolve("../outside_secret.txt")


def test_rejects_absolute_path_escape(sandbox):
    with pytest.raises(PathSecurityError):
        sandbox.resolve("/etc/passwd")


def test_rejects_nested_dotdot_traversal(sandbox):
    with pytest.raises(PathSecurityError):
        sandbox.resolve("src/../../outside_secret.txt")


def test_rejects_git_directory_access(sandbox):
    with pytest.raises(PathSecurityError):
        sandbox.resolve(".git/config")


def test_rejects_symlink_escape(sandbox, tmp_path):
    outside_dir = tmp_path.parent / "outside_dir"
    outside_dir.mkdir(exist_ok=True)
    (outside_dir / "secret.txt").write_text("secret")
    symlink = tmp_path / "escape_link"
    symlink.symlink_to(outside_dir)

    with pytest.raises(PathSecurityError):
        sandbox.resolve("escape_link/secret.txt")


def test_rejects_empty_path(sandbox):
    with pytest.raises(PathSecurityError):
        sandbox.resolve("")


def test_read_text_enforces_size_limit(sandbox, tmp_path):
    big_file = tmp_path / "big.txt"
    big_file.write_text("x" * 100)
    with pytest.raises(PathSecurityError):
        sandbox.read_text("big.txt", max_bytes=10)


def test_write_text_creates_file_within_workspace(sandbox, tmp_path):
    path = sandbox.write_text("src/new_module.py", "x = 1\n")
    assert path.read_text() == "x = 1\n"
    assert path.is_relative_to(tmp_path)


def test_write_text_rejects_escape(sandbox):
    with pytest.raises(PathSecurityError):
        sandbox.write_text("../escape.py", "x = 1\n")
