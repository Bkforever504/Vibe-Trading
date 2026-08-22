from __future__ import annotations

from datetime import date
import json

from scripts import trend_participation_shadow as shadow


def option(symbol: str, delta: float, strike: float, bid: float, ask: float, spread: float) -> dict:
    return {
        "option_symbol": symbol, "delta": delta, "strike": strike, "bid": bid, "ask": ask,
        "spread_pct": spread, "quote_scope": "indicative_modified_not_opra_nbbo",
    }


def test_qualification_requires_all_bullish_context_and_no_event_veto() -> None:
    ok, reasons = shadow.qualify_symbol(
        "SPY", {"primary_bias": "bullish", "intraday_alignment": "aligned"},
        {"state": "above_opening_range"}, {"classification": "bullish_lean", "risk_veto": {"active": False}},
        {"today": {"max_impact": "none", "caution_windows": []}},
    )
    assert ok is True
    assert reasons == []


def test_qualification_rejects_mixed_context() -> None:
    ok, reasons = shadow.qualify_symbol(
        "QQQ", {"primary_bias": "mixed", "intraday_alignment": "divergent"},
        {"state": "above_opening_range"}, {"classification": "bullish", "risk_veto": {"active": False}},
        {"today": {"max_impact": "none", "caution_windows": []}},
    )
    assert ok is False
    assert "higher_timeframes_not_bullish_aligned" in reasons


def test_selects_executable_defined_risk_debit_spread() -> None:
    rows = [
        option("SPY260812C00760000", 0.60, 760, 4.80, 4.90, 2.0),
        option("SPY260812C00765000", 0.33, 765, 2.45, 2.55, 4.0),
        option("SPY260812C00770000", 0.20, 770, 1.00, 1.10, 9.5),
    ]
    spread = shadow.select_call_debit_spread(rows, date(2026, 8, 4))
    assert spread is not None
    assert spread["entry_debit"] == 2.45
    assert spread["width"] == 5
    assert spread["max_loss_dollars"] == 245.0


def test_rejects_structure_over_maximum_debit() -> None:
    rows = [
        option("SPY260812C00760000", 0.60, 760, 5.90, 6.00, 2.0),
        option("SPY260812C00765000", 0.33, 765, 3.00, 3.10, 3.0),
    ]
    assert shadow.select_call_debit_spread(rows, date(2026, 8, 4)) is None


def test_design_day_cannot_be_recorded_as_forward_evidence(tmp_path) -> None:
    report = shadow.build_entry_report(date(2026, 8, 4), contract_fetcher=lambda *a, **k: [], log_path=tmp_path / "log.jsonl")
    assert report["status"] == "consumed_design_day_not_evidence"
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False


def test_executable_close_uses_long_bid_and_short_ask() -> None:
    candidate = {
        "spread": {
            "long": {"option_symbol": "LONG"},
            "short": {"option_symbol": "SHORT"},
        }
    }
    value = shadow.executable_close_value(candidate, {"LONG": {"bid": 4.5}, "SHORT": {"ask": 2.0}})
    assert value == 2.5


def test_mark_resolves_target_with_double_fee_pnl() -> None:
    candidate = {
        "session": "2026-08-05", "fee_per_leg_side": 0.66,
        "profit_target_close_value": 3.7, "stop_close_value": 1.225,
        "max_holding_calendar_days": 7,
        "spread": {"entry_debit": 2.45, "long": {"expiry": "2026-08-19"}},
    }
    result = shadow.evaluate_mark(candidate, 3.7, date(2026, 8, 6))
    assert result["reason"] == "profit_target"
    assert result["gross_pnl"] == 125.0
    assert result["pnl_base_fees"] == 122.36
    assert result["pnl_double_fees"] == 119.72


def test_mark_resolves_time_exit() -> None:
    candidate = {
        "session": "2026-08-05", "fee_per_leg_side": 0.66,
        "profit_target_close_value": 3.7, "stop_close_value": 1.225,
        "max_holding_calendar_days": 7,
        "spread": {"entry_debit": 2.45, "long": {"expiry": "2026-08-26"}},
    }
    assert shadow.evaluate_mark(candidate, 2.5, date(2026, 8, 12))["reason"] == "max_holding_time"


def test_entry_scan_records_no_candidate_heartbeat(tmp_path) -> None:
    log_path = tmp_path / "log.jsonl"
    report = shadow.build_entry_report(
        date(2026, 8, 18), contract_fetcher=lambda *a, **k: [], log_path=log_path,
    )

    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    heartbeat = rows[-1]
    assert report["status"] == "no_qualified_candidates"
    assert heartbeat["type"] == "scan_heartbeat"
    assert heartbeat["status"] == "no_qualified_candidates"
    assert heartbeat["execution_enabled"] is False
    assert heartbeat["can_submit_orders"] is False
