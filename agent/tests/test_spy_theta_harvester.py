from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from strategies.spy_theta_harvester import (
    OptionLegQuote,
    build_setup,
    entry_window_gate,
    load_shadow_state,
    management_math,
    monitor_shadow,
    quote_is_fresh,
    spread_economics,
    term_structure_gate,
)


ET = ZoneInfo("America/New_York")


def _prices(count: int = 100) -> list[float]:
    values = [700.0]
    for index in range(1, count):
        values.append(values[-1] * (1.002 if index % 2 else 0.998))
    return values


def _leg(
    symbol: str,
    *,
    expiry: str,
    strike: float,
    delta: float,
    bid: float,
    ask: float,
    now: datetime,
    iv: float = 0.30,
) -> OptionLegQuote:
    return OptionLegQuote(
        symbol=symbol,
        expiry=expiry,
        strike=strike,
        right="P",
        delta=delta,
        bid=bid,
        ask=ask,
        implied_volatility=iv,
        quote_timestamp=now.astimezone(timezone.utc).isoformat(),
    )


def _eligible_legs(now: datetime, *, expiry: str = "2026-09-25") -> list[OptionLegQuote]:
    return [
        _leg("SPY260925P00700000", expiry=expiry, strike=700.0, delta=0.16, bid=2.50, ask=2.55, now=now),
        _leg("SPY260925P00695000", expiry=expiry, strike=695.0, delta=0.08, bid=0.70, ask=0.75, now=now),
        _leg("SPY260925P00730000", expiry=expiry, strike=730.0, delta=0.50, bid=8.00, ask=8.10, now=now),
    ]


def _term(now: datetime) -> dict[str, object]:
    return {
        "source": "test",
        "date": now.date().isoformat(),
        "vix": 15.0,
        "vix3m": 17.0,
        "vix_over_vix3m": 15.0 / 17.0,
        "regime": "contango",
    }


def _qualified_iv_rank(now: datetime) -> dict[str, object]:
    return {
        "available": True,
        "status": "qualified",
        "as_of_date": now.date().isoformat(),
        "ivr": 55.0,
        "ivp": 65.0,
        "history_days": 252,
        "authority": "synthetic_test_fixture",
    }


def test_entry_is_monday_window_only() -> None:
    monday = datetime(2026, 8, 17, 9, 45, tzinfo=ET)
    sunday = datetime(2026, 8, 16, 9, 45, tzinfo=ET)
    late = datetime(2026, 8, 17, 21, 30, tzinfo=ET)

    assert entry_window_gate(monday)[0] is True
    assert entry_window_gate(sunday) == (False, "entry_day_not_monday")
    assert entry_window_gate(late) == (False, "outside_entry_window_0940_1015_et")


def test_term_structure_never_invents_contango() -> None:
    now = datetime(2026, 8, 17, 9, 45, tzinfo=ET)

    assert term_structure_gate({"available": False}, now_et=now) == (False, "vix_term_structure_unavailable")
    assert term_structure_gate({"date": "08/17/2026", "vix": 15.0, "vix3m": 17.0}, now_et=now)[0] is True
    assert term_structure_gate({"date": "2026-08-17", "vix": 18.0, "vix3m": 17.0}, now_et=now)[0] is False


def test_saved_35_cent_five_point_spread_fails_credit_quality() -> None:
    now = datetime(2026, 8, 10, 9, 45, tzinfo=ET)
    short = _leg("SPY260911P00733000", expiry="2026-09-11", strike=733, delta=0.16, bid=0.90, ask=0.95, now=now)
    long = _leg("SPY260911P00728000", expiry="2026-09-11", strike=728, delta=0.08, bid=0.50, ask=0.55, now=now)

    economics = spread_economics(short, long)

    assert economics["entry_credit"] == pytest.approx(0.35)
    assert economics["credit_to_width"] == pytest.approx(0.07)
    assert economics["credit_to_width"] < 0.33


def test_management_math_requires_two_thirds_wins_before_costs() -> None:
    result = management_math(0.35)

    assert result["profit_target_debit"] == pytest.approx(0.175)
    assert result["stop_debit"] == pytest.approx(0.70)
    assert result["profit_target_dollars"] == pytest.approx(17.50)
    assert result["stop_loss_dollars"] == pytest.approx(35.00)
    assert result["required_win_rate"] == pytest.approx(2 / 3)


def test_build_setup_passes_only_complete_executable_shadow_evidence() -> None:
    now = datetime(2026, 8, 17, 9, 45, tzinfo=ET)

    setup, decision = build_setup(
        now_et=now,
        legs=_eligible_legs(now),
        closes=_prices(),
        term_context=_term(now),
        iv_rank_context=_qualified_iv_rank(now),
    )

    assert setup is not None
    assert decision["status"] == "eligible"
    assert setup.entry_credit == pytest.approx(1.75)
    assert setup.midpoint_credit == pytest.approx(1.80)
    assert setup.credit_to_width == pytest.approx(0.35)
    assert setup.volatility_edge["event_data_complete"] is True
    assert setup.volatility_edge["execution_gates"] == {
        "measurement_complete": True,
        "iv_over_realized": True,
        "net_premium_positive": True,
        "event_data_complete": True,
    }
    assert setup.timeframe_confluence["authority"] == "shadow_attribution_only_no_execution"
    assert setup.timeframe_confluence["execution_effect"] == "none"
    assert setup.timeframe_confluence["dimensions"]["dte_bucket"] == "31-45dte"
    assert setup.timeframe_confluence["dimensions"]["maturity_matched_vrp_band"] != "unavailable"
    assert setup.timeframe_confluence["dimensions"]["ivr_band"] == "50_to_74_99"
    assert setup.execution_enabled is False
    assert setup.can_submit_orders is False
    assert setup.orders_submitted == 0


def test_cpi_on_expiry_blocks_even_high_credit_spread() -> None:
    now = datetime(2026, 8, 10, 9, 45, tzinfo=ET)
    legs = [
        _leg("SPY260911P00733000", expiry="2026-09-11", strike=733, delta=0.16, bid=2.50, ask=2.55, now=now),
        _leg("SPY260911P00728000", expiry="2026-09-11", strike=728, delta=0.08, bid=0.70, ask=0.75, now=now),
        _leg("SPY260911P00750000", expiry="2026-09-11", strike=750, delta=0.50, bid=8.00, ask=8.10, now=now),
    ]

    setup, decision = build_setup(now_et=now, legs=legs, closes=_prices(), term_context=_term(now))

    assert setup is None
    assert decision["reason"] == "high_impact_event_near_expiry"
    names = [row["name"] for row in decision["details"]["event_context"]["expiry_event_conflicts"]]
    assert any(name.startswith("CPI") for name in names)


def test_quote_freshness_requires_timestamp_and_valid_market() -> None:
    now = datetime(2026, 8, 17, 9, 45, tzinfo=ET)
    valid = _eligible_legs(now)[0]
    missing = OptionLegQuote(**{**asdict(valid), "quote_timestamp": None})
    crossed = OptionLegQuote(**{**asdict(valid), "bid": 3.0, "ask": 2.0})

    assert quote_is_fresh(valid, now_et=now) is True
    assert quote_is_fresh(missing, now_et=now) is False
    assert quote_is_fresh(crossed, now_et=now) is False


def test_monitor_marks_with_executable_close_and_closes_shadow(tmp_path: Path) -> None:
    now = datetime(2026, 8, 17, 9, 45, tzinfo=ET)
    setup, _ = build_setup(
        now_et=now,
        legs=_eligible_legs(now),
        closes=_prices(),
        term_context=_term(now),
        iv_rank_context=_qualified_iv_rank(now),
    )
    assert setup is not None
    state_path = tmp_path / "state.json"
    ledger_path = tmp_path / "ledger.jsonl"
    state_path.write_text(json.dumps(asdict(setup)), encoding="utf-8")
    quotes = {
        setup.short_symbol: _leg(setup.short_symbol, expiry=setup.expiry, strike=setup.short_strike, delta=0, bid=0.80, ask=0.85, now=now),
        setup.long_symbol: _leg(setup.long_symbol, expiry=setup.expiry, strike=setup.long_strike, delta=0, bid=0.20, ask=0.25, now=now),
    }

    result = monitor_shadow(state_path=state_path, ledger_path=ledger_path, now_et=now, quotes=quotes)
    saved = json.loads(state_path.read_text(encoding="utf-8"))

    assert result["reason"] == "close_profit_shadow"
    assert result["details"]["mark"]["executable_close_debit"] == pytest.approx(0.65)
    assert saved["status"] == "closed_shadow"
    assert saved["realized_shadow_pnl_dollars"] == pytest.approx(110.0)
    assert "close_shadow" in ledger_path.read_text(encoding="utf-8")


def test_monitor_closes_at_21_dte_with_executable_quote(tmp_path: Path) -> None:
    entry = datetime(2026, 8, 17, 9, 45, tzinfo=ET)
    setup, _ = build_setup(
        now_et=entry,
        legs=_eligible_legs(entry),
        closes=_prices(),
        term_context=_term(entry),
        iv_rank_context=_qualified_iv_rank(entry),
    )
    assert setup is not None
    monitor_at = datetime(2026, 9, 4, 9, 45, tzinfo=ET)
    state_path = tmp_path / "state.json"
    ledger_path = tmp_path / "ledger.jsonl"
    state_path.write_text(json.dumps(asdict(setup)), encoding="utf-8")
    quotes = {
        setup.short_symbol: _leg(setup.short_symbol, expiry=setup.expiry, strike=setup.short_strike, delta=0, bid=2.4, ask=2.5, now=monitor_at),
        setup.long_symbol: _leg(setup.long_symbol, expiry=setup.expiry, strike=setup.long_strike, delta=0, bid=0.6, ask=0.7, now=monitor_at),
    }

    result = monitor_shadow(
        state_path=state_path,
        ledger_path=ledger_path,
        now_et=monitor_at,
        quotes=quotes,
    )

    assert result["reason"] == "close_time_shadow"
    assert result["details"]["mark"]["dte_remaining"] == 21
    assert result["details"]["mark"]["executable_close_debit"] == pytest.approx(1.9)


def test_legacy_midpoint_setup_is_not_an_open_position(tmp_path: Path) -> None:
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps({"symbol": "SPY", "credit": 0.35}), encoding="utf-8")

    state = load_shadow_state(path)

    assert state["status"] == "legacy_unconfirmed"


def test_entry_and_monitor_runners_preserve_separate_decisions() -> None:
    root = Path(__file__).resolve().parents[2]
    entry = (root / "scripts" / "run_spy_theta_harvester.ps1").read_text(encoding="utf-8")
    monitor = (root / "scripts" / "run_spy_theta_harvester_monitor.ps1").read_text(encoding="utf-8")

    assert "theta_harvester_entry_decision.json" in entry
    assert "theta_harvester_monitor_decision.json" in monitor
    assert "theta_harvester_setup.json" not in monitor
    assert "--check" in monitor
