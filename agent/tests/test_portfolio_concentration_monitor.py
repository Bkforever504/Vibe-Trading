from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import portfolio_concentration_monitor as monitor


def test_option_direction_handles_calls_and_puts() -> None:
    assert monitor._option_direction("SPY260630C00747000", 1) == "bullish"
    assert monitor._option_direction("SPY260630C00747000", -1) == "bearish"
    assert monitor._option_direction("TSLA260703P00300000", 1) == "bearish"
    assert monitor._option_direction("TSLA260703P00300000", -1) == "bullish"


def test_analyze_concentration_rolls_up_directional_beta() -> None:
    account = {"equity": 100_000}
    positions = [
        {
            "symbol": "SPY260630C00747000",
            "underlying": "SPY",
            "market_value": 1_000,
            "unrealized_pl": 100,
            "direction": "bullish",
        },
        {
            "symbol": "QQQ260630P00500000",
            "underlying": "QQQ",
            "market_value": -2_000,
            "unrealized_pl": -50,
            "direction": "bearish",
        },
    ]

    result = monitor.analyze_concentration(account, positions)

    assert result["position_count"] == 2
    assert result["gross_market_value"] == 3000
    assert result["net_directional_beta_dollars"] == -1400
    assert result["net_directional_beta_pct_equity"] == -1.4
    assert result["risk_level"] == "normal"


def test_append_and_write_report(tmp_path: Path) -> None:
    report = {"date": "2026-06-30", "concentration": {"risk_level": "normal"}}
    log_path = tmp_path / "log.jsonl"
    report_path = tmp_path / "report.json"

    monitor.append_log(report, log_path)
    monitor.write_report(report, report_path)

    assert json.loads(log_path.read_text(encoding="utf-8"))["date"] == "2026-06-30"
    assert json.loads(report_path.read_text(encoding="utf-8"))["concentration"]["risk_level"] == "normal"
