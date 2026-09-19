import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from calculator import add, divide, multiply, subtract  # noqa: E402


def test_add():
    assert add(2, 3) == 5


def test_subtract():
    assert subtract(5, 3) == 2


def test_multiply():
    assert multiply(4, 3) == 12


def test_divide():
    assert divide(10, 2) == 5


def test_divide_by_zero_raises():
    try:
        divide(1, 0)
    except ValueError:
        pass
    else:
        raise AssertionError("Forventede ValueError")
