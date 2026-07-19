from __future__ import annotations

import json
from pathlib import Path

from scripts import flip_path_telemetry_completeness as report


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _sample(event: str, trade_id: str = "t1") -> dict:
    return {
        "event": event,
        "trade_id": trade_id,
        "order_id": "o1",
        "contract": "SPY260714C00750000",
        "quote": {"bid": 1.0, "ask": 1.1},
        "provenance": {"status": "ok"},
    }


def test_complete_requires_observed_fields_and_quote_events(tmp_path: Path) -> None:
    trades = tmp_path / "trades.json"
    samples = tmp_path / "samples.jsonl"
    _write_json(trades, [{
        "id": "t1", "alpaca_order_id": "o1", "status": "closed", "symbol": "SPY",
        "option_symbol": "SPY260714C00750000", "entry_at": "2026-07-14T14:30:00Z",
        "exit_at": "2026-07-14T15:30:00Z", "best_pnl_pct": 50.0, "worst_pnl_pct": -10.0,
    }])
    _write_jsonl(samples, [_sample("fill"), _sample("monitor"), _sample("exit")])

    built = report.build_report(trades, samples)

    assert built["execution_enabled"] is False
    assert built["can_submit_orders"] is False
    assert built["observed_complete_count"] == 1
    assert built["trades"][0]["status"] == "complete"


def test_synthetic_legacy_fields_do_not_count_as_complete(tmp_path: Path) -> None:
    trades = tmp_path / "trades.json"
    samples = tmp_path / "samples.jsonl"
    _write_json(trades, [{
        "id": "t1", "alpaca_order_id": "o1", "status": "closed", "symbol": "SPY",
        "option_symbol": "SPY260714C00750000", "entry_at": "2026-07-14T14:30:00Z",
        "exit_at": "2026-07-14T15:30:00Z", "best_pnl_pct": 50.0, "worst_pnl_pct": -10.0,
        "_backfilled_fields": ["entry_at", "exit_at", "best_pnl_pct", "worst_pnl_pct"],
    }])
    _write_jsonl(samples, [_sample("fill"), _sample("monitor"), _sample("exit")])

    built = report.build_report(trades, samples)

    assert built["observed_complete_count"] == 0
    assert built["synthetic_legacy_count"] == 1
    assert built["trades"][0]["synthetic_fields"] == ["best_pnl_pct", "entry_at", "exit_at", "worst_pnl_pct"]


def test_missing_quote_event_keeps_trade_incomplete(tmp_path: Path) -> None:
    trades = tmp_path / "trades.json"
    samples = tmp_path / "samples.jsonl"
    _write_json(trades, [{
        "id": "t1", "alpaca_order_id": "o1", "status": "closed", "symbol": "SPY",
        "option_symbol": "SPY260714C00750000", "entry_at": "2026-07-14T14:30:00Z",
        "exit_at": "2026-07-14T15:30:00Z", "best_pnl_pct": 50.0, "worst_pnl_pct": -10.0,
    }])
    _write_jsonl(samples, [_sample("fill"), _sample("exit")])

    built = report.build_report(trades, samples)

    assert built["observed_complete_count"] == 0
    assert built["trades"][0]["missing_quote_events"] == ["monitor"]
