import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from report import build_report  # noqa: E402


def test_build_report():
    result = build_report([{"amount": 10}, {"amount": 5}])
    assert result == {"transaction_count": 2, "total_amount": 15}
