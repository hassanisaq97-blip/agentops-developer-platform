import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from eligibility import is_eligible  # noqa: E402


def test_negative_age_is_never_eligible():
    assert is_eligible(-5, 18) is False


def test_adult_is_eligible():
    assert is_eligible(20, 18) is True
