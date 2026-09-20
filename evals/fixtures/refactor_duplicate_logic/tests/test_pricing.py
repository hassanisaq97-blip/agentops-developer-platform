import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pricing import price_with_tax, price_with_tax_and_shipping  # noqa: E402


def test_price_with_tax():
    assert price_with_tax(100, 0.25) == 125


def test_price_with_tax_and_shipping():
    assert price_with_tax_and_shipping(100, 0.25, 10) == 135
