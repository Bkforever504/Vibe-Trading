"""Tests for research/options_limit_execution_lab.py."""
from __future__ import annotations

import json
from pathlib import Path

from research import options_limit_execution_lab as lab


def _rows(lid: str, date: str, entry_ts: str, entry_bid: float, entry_ask: float,
          forward: list[tuple[str, float, float]]) -> list[dict]:
    base = {"lifecycle_id": lid, "date": date, "symbol": "SPY",
            "day_type": "trend", "strategy": "0dte", "right": "CALL"}
    out = [{**base, "event_type": "shadow_entry", "scanned_at": entry_ts,
            "entry_price_est": (entry_bid + entry_ask) / 2.0,
            "selection_bid": entry_bid, "selection_ask": entry_ask,
            "mark_price": (entry_bid + entry_ask) / 2.0}]
    for ts, bid, ask in forward:
        out.append({**base, "event_type": "shadow_mark", "scanned_at": ts,
                    "selection_bid": bid, "selection_ask": ask,
                    "mark_price": (bid + ask) / 2.0})
    out.append({**base, "event_type": "shadow_exit", "scanned_at": forward[-1][0],
                "selection_bid": forward[-1][1], "selection_ask": forward[-1][2],
                "mark_price": (forward[-1][1] + forward[-1][2]) / 2.0})
    return out


def _write(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "shadow.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return p


def test_aggressive_ask_always_fills(tmp_path):
    rows = _rows("a", "2026-01-01", "2026-01-01T09:30:00", 1.0, 1.1, [
        ("2026-01-01T09:35:00", 1.4, 1.5),
    ])
    p = _write(tmp_path, rows)
    lives = lab.load_lifecycles(p)
    assert len(lives) == 1
    filled, fill_price, ret = lab._policy_aggressive_ask(lives[0])
    assert filled is True
    assert fill_price == 1.1
    # realized = (1.4 - 1.1) / 1.1 * 100 = 27.27%
    assert abs(ret - 27.27) < 0.05


def test_patient_bid_fills_only_when_ask_crosses_down(tmp_path):
    # ask stays above 1.0, so bid limit never fills
    rows = _rows("a", "2026-01-01", "2026-01-01T09:30:00", 1.0, 1.1, [
        ("2026-01-01T09:35:00", 1.05, 1.15),
        ("2026-01-01T09:40:00", 1.05, 1.15),
    ])
    p = _write(tmp_path, rows)
    lives = lab.load_lifecycles(p)
    filled, _, ret = lab._policy_patient(lives[0], limit_price=1.0)
    assert filled is False
    assert ret == 0.0


def test_patient_bid_fills_when_ask_drops(tmp_path):
    rows = _rows("a", "2026-01-01", "2026-01-01T09:30:00", 1.0, 1.1, [
        ("2026-01-01T09:35:00", 0.95, 1.00),  # ask hits 1.00 <= bid limit 1.0
        ("2026-01-01T09:40:00", 1.20, 1.25),
    ])
    p = _write(tmp_path, rows)
    lives = lab.load_lifecycles(p)
    filled, fill_price, ret = lab._policy_patient(lives[0], limit_price=1.0)
    assert filled is True
    assert fill_price == 1.0
    # realized = (1.20 - 1.00) / 1.00 * 100 = 20.0
    assert abs(ret - 20.0) < 0.1


def test_report_read_only_flags(tmp_path):
    rows = _rows("a", "2026-01-01", "2026-01-01T09:30:00", 1.0, 1.1, [
        ("2026-01-01T09:35:00", 1.2, 1.3),
    ])
    p = _write(tmp_path, rows)
    report = lab.build_report(candidates_path=p)
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["automatic_parameter_changes"] is False
    assert report["promotion_authority"] == "shadow_challenger_only"
    assert report["total_lifecycles"] == 1


def test_adverse_selection_reports_horizon_bins(tmp_path):
    rows = _rows("a", "2026-01-01", "2026-01-01T09:30:00", 1.0, 1.1, [
        ("2026-01-01T09:45:00", 1.5, 1.6),  # +15min post-entry
        ("2026-01-01T10:31:00", 2.0, 2.1),  # +60min
    ])
    p = _write(tmp_path, rows)
    report = lab.build_report(candidates_path=p)
    stats = report["adverse_selection"]
    assert stats["15m_bid_return_vs_entry_ask"]["n"] == 1
    assert stats["60m_bid_return_vs_entry_ask"]["n"] == 1
