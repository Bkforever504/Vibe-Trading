from __future__ import annotations

import json
from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from scripts import market_schedule_alignment as alignment
from scripts import portfolio_theta_dashboard as dashboard
from strategies import spy_weekend_vol as weekend
from strategies import spy_wheel as wheel
from strategies import vix_call_hedge as vix


def _wheel_state(**overrides):
    values = {
        "shadow_id": "wheel-1",
        "generated_at": "2026-08-11T14:00:00+00:00",
        "phase": "csp_open",
        "symbol": "SPY",
        "cost_basis": 0.0,
        "shares_held": 0,
        "leg_type": "put",
        "leg_expiry": (date.today() + timedelta(days=10)).isoformat(),
        "leg_strike": 500.0,
        "leg_entry_credit": 2.0,
        "leg_profit_target": 1.0,
        "leg_opened_at": "2026-08-11T14:00:00+00:00",
        "total_premium_collected": 2.0,
        "cycles_completed": 0,
    }
    values.update(overrides)
    return wheel.WheelState(**values)


def test_wheel_blocks_csp_above_configured_cash(monkeypatch) -> None:
    monkeypatch.setattr(wheel, "yf", object())
    monkeypatch.setattr(wheel, "PAPER_ACCOUNT_SIZE", 10_000.0)
    monkeypatch.setattr(wheel, "_get_vix", lambda: 18.0)
    monkeypatch.setattr(wheel, "_get_ivr", lambda _symbol: 40.0)
    monkeypatch.setattr(wheel, "_find_expiry", lambda _symbol: "2026-09-04")
    monkeypatch.setattr(wheel, "_find_put_strike", lambda *_args: (753.0, 4.0, 0.30))
    wheel.yf = SimpleNamespace(Ticker=lambda _symbol: SimpleNamespace(fast_info={"lastPrice": 760.0}))

    setup, decision = wheel.sell_put("SPY", _wheel_state(phase="idle", leg_type=None))

    assert setup is None
    assert decision["reason"] == "insufficient_cash_for_cash_secured_put"
    assert decision["details"]["cash_requirement"] == 75_300.0


def test_wheel_main_preserves_idle_state_when_scan_is_blocked(monkeypatch, tmp_path) -> None:
    state_path = tmp_path / "state.json"
    ledger_path = tmp_path / "ledger.jsonl"
    out_path = tmp_path / "decision.json"
    state = _wheel_state(phase="idle", leg_type=None, leg_strike=None, leg_expiry=None)
    state_path.write_text(json.dumps(wheel.asdict(state)), encoding="utf-8")
    monkeypatch.setattr(
        wheel,
        "sell_put",
        lambda _symbol, _state: (None, wheel._decision("blocked", "no_setup")),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            str(wheel.__file__),
            "--state", str(state_path),
            "--ledger", str(ledger_path),
            "--out", str(out_path),
        ],
    )

    wheel.main()

    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert saved["phase"] == "idle"
    assert json.loads(out_path.read_text(encoding="utf-8"))["reason"] == "no_setup"


def test_wheel_profit_close_uses_ask_and_advances_state(monkeypatch) -> None:
    chain = SimpleNamespace(
        puts=pd.DataFrame([{"strike": 500.0, "bid": 0.80, "ask": 0.90}]),
        calls=pd.DataFrame(),
    )
    ticker = SimpleNamespace(fast_info={"lastPrice": 510.0}, option_chain=lambda _expiry: chain)
    monkeypatch.setattr(wheel, "yf", SimpleNamespace(Ticker=lambda _symbol: ticker))
    state = _wheel_state()

    updated, decision = wheel.check_and_advance("SPY", state)

    assert decision["status"] == "close_profit"
    assert decision["details"]["executable_close_debit"] == pytest.approx(0.90)
    assert updated.phase == "idle"
    assert updated.leg_strike is None


def test_wheel_expired_itm_put_becomes_assignment(monkeypatch) -> None:
    chain = SimpleNamespace(puts=pd.DataFrame(), calls=pd.DataFrame())
    ticker = SimpleNamespace(fast_info={"lastPrice": 490.0}, option_chain=lambda _expiry: chain)
    monkeypatch.setattr(wheel, "yf", SimpleNamespace(Ticker=lambda _symbol: ticker))
    state = _wheel_state(leg_expiry=date.today().isoformat())

    updated, decision = wheel.check_and_advance("SPY", state)

    assert decision["status"] == "assigned"
    assert updated.phase == "assigned"
    assert updated.shares_held == 100


def test_dashboard_excludes_infeasible_wheel_collateral() -> None:
    result = dashboard._position_theta(
        {"name": "wheel", "type": "wheel", "active_phases": ["csp_open"]},
        {
            "phase": "csp_open",
            "leg_strike": 753.0,
            "leg_entry_credit": 4.13,
            "leg_expiry": "2026-09-04",
        },
        account_size=10_000.0,
    )

    assert result["active"] is False
    assert result["daily_theta"] == 0.0
    assert result["note"] == "excluded_insufficient_cash_secured_collateral"


def test_weekend_entry_pays_asks_not_midpoints(monkeypatch) -> None:
    chain = SimpleNamespace(
        calls=pd.DataFrame([{"strike": 500.0, "bid": 4.0, "ask": 4.3}]),
        puts=pd.DataFrame([{"strike": 500.0, "bid": 3.0, "ask": 3.2}]),
    )
    monkeypatch.setattr(
        weekend,
        "yf",
        SimpleNamespace(Ticker=lambda _symbol: SimpleNamespace(option_chain=lambda _expiry: chain)),
    )

    priced = weekend._price_straddle("2026-08-14", 500.0)

    assert priced == (500.0, 4.3, 3.2)


def test_new_tasks_use_correct_central_times_and_limited_privilege() -> None:
    assert alignment.EXPECTED_TASKS[r"\SPY-Wheel-Check"] == {"08:45"}
    assert alignment.EXPECTED_TASKS[r"\SPY-Weekend-Vol-Entry"] == {"13:35"}
    assert alignment.EXPECTED_TASKS[r"\SPY-Weekend-Vol-Monitor"] == {"08:50", "13:05", "14:05"}
    text = (wheel.ROOT / "scripts" / "register_new_strategies_tasks.ps1").read_text(encoding="utf-8")
    assert "-RunLevel Limited" in text
    assert "-RunLevel Highest" not in text
    assert "run_spy_weekend_vol_monitor.ps1" in text


def test_vix_existing_open_state_is_checked_not_reopened(monkeypatch, tmp_path) -> None:
    state = vix.HedgeSetup(
        shadow_id="vix-1", generated_at="2026-08-11T14:00:00+00:00",
        status="open_shadow", vix_at_entry=16.0, vix3m_at_entry=18.0,
        target_strike=24.0, actual_strike=25.0, expiry="2026-10-01", dte=51,
        call_mid=1.0, contracts=1, total_cost=100.0, notional_protected=10_000.0,
        roll_at_dte=21,
    )
    state_path = tmp_path / "state.json"
    out_path = tmp_path / "decision.json"
    ledger_path = tmp_path / "ledger.jsonl"
    state_path.write_text(json.dumps(vix.asdict(state)), encoding="utf-8")
    monkeypatch.setattr(vix, "check_hedge", lambda _setup: vix._decision("hold", "still_open"))
    monkeypatch.setattr(vix, "build_hedge", lambda *_args: pytest.fail("must not reopen"))
    monkeypatch.setattr(
        "sys.argv",
        [str(vix.__file__), "--state", str(state_path), "--ledger", str(ledger_path), "--out", str(out_path)],
    )

    vix.main()

    assert json.loads(out_path.read_text(encoding="utf-8"))["reason"] == "still_open"
    assert not ledger_path.exists()


def test_vix_hedge_cost_is_bounded_by_account_budget(monkeypatch) -> None:
    calls = pd.DataFrame([
        {"strike": 25.0, "bid": 0.90, "ask": 1.00},
    ])
    ticker = SimpleNamespace(
        options=[(date.today() + timedelta(days=50)).isoformat()],
        option_chain=lambda _expiry: SimpleNamespace(calls=calls),
    )
    monkeypatch.setattr(vix, "yf", SimpleNamespace(Ticker=lambda _symbol: ticker))
    monkeypatch.setattr(vix, "_get_vix_term", lambda: (16.0, 18.0))
    monkeypatch.setattr(vix, "_current_short_premium_notional", lambda: 10_000.0)
    monkeypatch.setattr(vix, "PAPER_ACCOUNT_SIZE", 10_000.0)
    monkeypatch.setattr(vix, "MAX_HEDGE_COST_PCT", 0.005)

    setup, decision = vix.build_hedge()

    assert setup is None
    assert decision["reason"] == "vix_hedge_exceeds_portfolio_cost_budget"
    assert decision["details"]["total_cost"] == 100.0
    assert decision["details"]["max_total_cost"] == 50.0
