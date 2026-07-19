from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import bot_status_snapshot as snapshot


def test_build_snapshot_rolls_up_reports(monkeypatch) -> None:
    monkeypatch.setattr(snapshot, "_trade_counts", lambda: {"flip": {"open": 1, "closed": 1, "total": 2}, "iwm_options": {"open": 0, "closed": 1, "total": 1}})
    monkeypatch.setattr(snapshot, "_guard_block_counts", lambda: {"alpaca": 2, "kalshi": 0})

    report = snapshot.build_snapshot(
        generated_at=datetime(2026, 6, 30, 20, tzinfo=timezone.utc),
        health_report={"summary": {"ok": 12, "stale": 0, "missing": 0, "error": 0}},
        market_force={"classification": "bullish_lean", "total_score": 2.25, "confidence": 9.25},
        exposure={"posture": "normal", "score": 8.0, "advisory_settings": {"max_new_trades": 2}},
        concentration={
            "account": {"equity": 90000, "day_change": 450, "buying_power": 100000},
            "concentration": {
                "risk_level": "normal",
                "position_count": 2,
                "gross_pct_equity": 1.2,
                "net_directional_beta_pct_equity": 0.7,
                "warnings": [],
            },
        },
        options_state={"trades": []},
        outcome={"verdict": "posture_helpful", "review_score": 7.5, "event_summary": {"realized_pnl": 488, "guard_block_count": 8}},
    )

    assert report["status"] == "normal"
    assert report["health"]["status"] == "ok"
    assert report["market_force"]["classification"] == "bullish_lean"
    assert report["portfolio_concentration"]["risk_level"] == "normal"
    assert report["open_trades"]["flip"]["open"] == 1


def test_build_snapshot_flags_high_concentration(monkeypatch) -> None:
    monkeypatch.setattr(snapshot, "_trade_counts", lambda: {"flip": {"open": 0, "closed": 0, "total": 0}, "iwm_options": {"open": 0, "closed": 0, "total": 0}})
    monkeypatch.setattr(snapshot, "_guard_block_counts", lambda: {"alpaca": 0, "kalshi": 0})

    report = snapshot.build_snapshot(
        generated_at=datetime(2026, 6, 30, 20, tzinfo=timezone.utc),
        health_report={"summary": {"ok": 10, "stale": 0, "missing": 1, "error": 0}},
        concentration={"account": {}, "concentration": {"risk_level": "high", "warnings": ["gross_option_value_above_5pct_equity"]}},
        options_state={"trades": []},
    )

    assert report["status"] == "watch"
    assert "health_missing" in report["status_flags"]
    assert "concentration_high" in report["status_flags"]


def test_build_snapshot_requires_review_when_option_state_disagrees_with_broker(monkeypatch) -> None:
    monkeypatch.setattr(snapshot, "_trade_counts", lambda: {"flip": {"open": 0}, "iwm_options": {"open": 1}})
    monkeypatch.setattr(snapshot, "_guard_block_counts", lambda: {"alpaca": 0, "kalshi": 0})

    report = snapshot.build_snapshot(
        generated_at=datetime(2026, 7, 10, 1, tzinfo=timezone.utc),
        health_report={"summary": {"ok": 44, "stale": 0, "missing": 0, "error": 0}},
        concentration={
            "account": {},
            "concentration": {
                "risk_level": "normal",
                "warnings": [],
                "positions": [
                    {"symbol": "IWM260807C00313000"},
                    {"symbol": "IWM260807C00317500"},
                ],
            },
        },
        options_state={
            "trades": [
                {
                    "id": "active",
                    "status": "open",
                    "legs": ["IWM260807C00313000", "IWM260807P00277000"],
                },
                {
                    "id": "closed",
                    "status": "closed",
                    "legs": ["IWM260807C00317500"],
                },
            ]
        },
    )

    integrity = report["option_position_integrity"]
    assert report["status"] == "review_required"
    assert integrity["missing_active_legs"] == ["IWM260807P00277000"]
    assert integrity["untracked_broker_legs"] == ["IWM260807C00317500"]
    assert integrity["closed_trade_legs_still_open"] == ["IWM260807C00317500"]
    assert "option_position_integrity_review_required" in report["status_flags"]
