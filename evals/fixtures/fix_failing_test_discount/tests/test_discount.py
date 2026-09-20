import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from discount import total_with_loyalty_bonus  # noqa: E402


def test_total_with_loyalty_bonus():
    assert total_with_loyalty_bonus(100, 20) == 120
