from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import moondev_liquidation_context_scanner as scanner


def test_scan_without_api_key_is_read_only_auth_missing(monkeypatch) -> None:
    monkeypatch.delenv("MOONDEV_API_KEY", raising=False)

    report = scanner.scan_moondev_context(api_key=None)

    assert report["status"] == "auth_missing"
    assert report["execution_enabled"] is False
    assert report["live_trading_allowed"] is False
    assert "MOONDEV_API_KEY" in report["summary"]


def test_scan_normalizes_liquidation_and_hlp_context(monkeypatch) -> None:
    responses = {
        "/api/all_liquidations/1h.json": {
            "liquidations": [
                {"symbol": "BTCUSDT", "side": "short", "usd_value": 80_000_000},
                {"symbol": "ETHUSDT", "side": "short", "usd_value": 60_000_000},
                {"symbol": "SOLUSDT", "side": "long", "usd_value": 10_000_000},
            ]
        },
        "/api/all_liquidations/stats.json": {},
        "/api/hlp/sentiment": {
            "z_score": 2.4,
            "signal": "Retail heavily short; squeeze risk.",
            "net_delta": 12345,
            "percentile": 94,
        },
        "/api/position_snapshots/stats": {
            "overall": {"total_snapshots": 100, "unique_users": 25, "avg_distance_pct": 6.2},
            "by_symbol": {"BTC": {"snapshots": 40}},
            "top_10_closest": [{"symbol": "BTC", "side": "short", "distance_pct": 1.4}],
        },
        "/api/poly/whales": {
            "trades": [
                {"side": "BUY", "usd_amount": 8000},
                {"side": "SELL", "usd_amount": 3000},
            ]
        },
    }

    def fake_get(endpoint, *, api_key, params=None):
        assert api_key == "key"
        return responses[endpoint]

    monkeypatch.setattr(scanner, "_get_json", fake_get)

    report = scanner.scan_moondev_context(api_key="key")

    assert report["status"] == "ok"
    assert report["liquidation_pressure"] == "short_squeeze_pressure"
    assert report["liquidations"]["total_volume_usd"] == 150_000_000
    assert report["hlp_sentiment"]["bias"] == "retail_short_squeeze_risk"
    assert report["position_snapshots"]["total_snapshots"] == 100
    assert report["polymarket_whales"]["net_buy_usd"] == 5000
    assert report["market_bias"] == "crypto_stress_watch"


def test_write_report_and_log_are_json_serializable(tmp_path: Path) -> None:
    row = scanner.scan_moondev_context(api_key=None)
    log_path = tmp_path / "moondev.jsonl"
    report_path = tmp_path / "moondev.json"

    scanner.append_log(row, log_path)
    scanner.write_report(row, report_path)

    assert json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])["provider"] == "moondev_liquidation_context"
    assert json.loads(report_path.read_text(encoding="utf-8"))["execution_enabled"] is False
