import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from formatter import title_case, truncate  # noqa: E402


def test_truncate():
    assert truncate("hello world", 5) == "hello"


def test_title_case():
    assert title_case("hello world") == "Hello World"
