from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from strategies import spy_0dte_pm_spread as pm
from strategies import spy_iron_condor as ic


def _chain() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "contractSymbol": "SPY260811P00600000",
            "strike": 600.0,
            "bid": 1.00,
            "ask": 1.20,
        },
        {
            "contractSymbol": "SPY260811P00595000",
            "strike": 595.0,
            "bid": 0.20,
            "ask": 0.30,
        },
    ])


def test_0dte_spread_uses_executable_two_leg_entry_and_close() -> None:
    market = pm.spread_market_from_chain(_chain(), 600.0, 595.0)

    assert market is not None
    assert market["executable_entry_credit"] == pytest.approx(0.70)
    assert market["midpoint_credit"] == pytest.approx(0.85)
    assert market["executable_close_debit"] == pytest.approx(1.00)
    assert market["executable_entry_credit"] != pytest.approx(1.00)


def test_iron_condor_leg_spread_uses_executable_sides() -> None:
    market = ic.spread_market_from_chain(_chain(), 600.0, 595.0)

    assert market is not None
    assert market["executable_entry_credit"] == pytest.approx(0.70)
    assert market["executable_close_debit"] == pytest.approx(1.00)
    assert market["short_symbol"] == "SPY260811P00600000"
    assert market["long_symbol"] == "SPY260811P00595000"


def test_0dte_selector_skips_unpriceable_target_delta_pair() -> None:
    chain = pd.DataFrame([
        {"contractSymbol": "P605", "strike": 605.0, "bid": 0.20, "ask": 0.30, "delta": -0.16},
        {"contractSymbol": "P600", "strike": 600.0, "bid": 0.40, "ask": 0.50, "delta": -0.14},
        {"contractSymbol": "P595", "strike": 595.0, "bid": 0.10, "ask": 0.20, "delta": -0.12},
    ])

    selected, diagnostics = pm.select_priceable_put_spread(
        chain, expiry="2026-08-11", spot=610.0, vix=18.0
    )

    assert selected is not None
    assert selected["short_strike"] == pytest.approx(600.0)
    assert selected["long_strike"] == pytest.approx(595.0)
    assert diagnostics["unpriceable_count"] == 1


@pytest.mark.parametrize("right", ["put", "call"])
def test_iron_condor_selector_skips_unpriceable_target_delta_pair(right) -> None:
    if right == "put":
        rows = [
            {"contractSymbol": "P600", "strike": 600.0, "bid": 0.20, "ask": 0.30, "delta": -0.16},
            {"contractSymbol": "P595", "strike": 595.0, "bid": 0.40, "ask": 0.50, "delta": -0.14},
            {"contractSymbol": "P590", "strike": 590.0, "bid": 0.10, "ask": 0.20, "delta": -0.12},
        ]
        expected = (595.0, 590.0)
    else:
        rows = [
            {"contractSymbol": "C620", "strike": 620.0, "bid": 0.20, "ask": 0.30, "delta": 0.16},
            {"contractSymbol": "C625", "strike": 625.0, "bid": 0.40, "ask": 0.50, "delta": 0.14},
            {"contractSymbol": "C630", "strike": 630.0, "bid": 0.10, "ask": 0.20, "delta": 0.12},
        ]
        expected = (625.0, 630.0)

    selected, diagnostics = ic.select_priceable_wing(
        pd.DataFrame(rows), spot=610.0, sigma=0.18, T=25 / 252, right=right
    )

    assert selected is not None
    assert (selected["short_strike"], selected["long_strike"]) == expected
    assert diagnostics["unpriceable_count"] == 1


def test_equal_width_condor_max_loss_is_not_sum_of_both_wings() -> None:
    assert ic.combined_max_loss(5.0, 1.40) == pytest.approx(3.60)
    assert ic.combined_max_loss(5.0, 1.40) != pytest.approx((5.0 - 0.70) * 2)


def test_crossed_market_is_rejected() -> None:
    chain = _chain()
    chain.loc[0, "ask"] = 0.90

    assert pm.spread_market_from_chain(chain, 600.0, 595.0) is None
    assert ic.spread_market_from_chain(chain, 600.0, 595.0) is None


@pytest.mark.parametrize("module", [pm, ic])
def test_executable_close_decision_persists_closed_shadow(module, tmp_path) -> None:
    state_path = tmp_path / "state.json"
    ledger_path = tmp_path / "ledger.jsonl"
    state = {"shadow_id": "shadow-1", "status": "open_shadow"}
    decision = module._decision(
        "close_profit",
        "target_hit",
        current_debit=0.40,
        pnl=0.60,
        pnl_pct=0.60,
    )

    module.apply_monitor_decision(
        state,
        decision,
        state_path=state_path,
        ledger_path=ledger_path,
    )

    saved = json.loads(state_path.read_text(encoding="utf-8"))
    ledger = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()]
    assert saved["status"] == "closed_shadow"
    assert saved["closing_debit"] == pytest.approx(0.40)
    assert saved["realized_shadow_pnl"] == pytest.approx(0.60)
    assert ledger[-1]["type"] == "close_shadow"
    assert ledger[-1]["execution_enabled"] is False


@pytest.mark.parametrize("module", [pm, ic])
def test_blocked_monitor_decision_never_closes_shadow(module, tmp_path) -> None:
    state_path = tmp_path / "state.json"
    ledger_path = tmp_path / "ledger.jsonl"
    state = {"shadow_id": "shadow-1", "status": "open_shadow"}

    module.apply_monitor_decision(
        state,
        module._decision("blocked", "monitor_spread_quote_unavailable"),
        state_path=state_path,
        ledger_path=ledger_path,
    )

    saved = json.loads(state_path.read_text(encoding="utf-8"))
    ledger = json.loads(ledger_path.read_text(encoding="utf-8").splitlines()[-1])
    assert saved["status"] == "open_shadow"
    assert ledger["type"] == "mark_shadow"


@pytest.mark.parametrize("module", [pm, ic])
def test_legacy_state_without_executable_fields_fails_closed(module) -> None:
    setup, decision = module.setup_from_state({"shadow_id": "legacy", "status": "open_shadow"})

    assert setup is None
    assert decision is not None
    assert decision["status"] == "blocked"
    assert decision["reason"] == "legacy_state_missing_execution_fields"


def test_iron_condor_dte_close_requires_executable_quote(monkeypatch) -> None:
    class _Chain:
        puts = pd.DataFrame()
        calls = pd.DataFrame()

    class _Ticker:
        def option_chain(self, _expiry):
            return _Chain()

    class _YF:
        @staticmethod
        def Ticker(_symbol):
            return _Ticker()

    monkeypatch.setattr(ic, "yf", _YF())
    setup = ic.IronCondorSetup(
        shadow_id="ic-1", generated_at="2026-08-11T14:00:00+00:00", status="open_shadow",
        symbol="SPY", expiry="2026-09-01", dte=21,
        short_put_symbol="SPY260901P00600000", long_put_symbol="SPY260901P00595000",
        short_call_symbol="SPY260901C00620000", long_call_symbol="SPY260901C00625000",
        short_put=600.0, long_put=595.0, short_call=620.0, long_call=625.0,
        put_delta=-0.16, call_delta=0.16, put_credit=0.70, call_credit=0.70,
        total_credit=1.40, midpoint_credit=1.60,
        short_put_bid=1.0, short_put_ask=1.2, long_put_bid=0.2, long_put_ask=0.3,
        short_call_bid=1.0, short_call_ask=1.2, long_call_bid=0.2, long_call_ask=0.3,
        quote_captured_at="2026-08-11T14:00:00+00:00",
        max_loss_put_wing=3.60, max_loss_call_wing=3.60, max_loss_total=3.60,
        profit_target=0.70, close_at_dte=21, vix_at_entry=17.0, vix3m_at_entry=19.0,
        ivr_at_entry=40.0, ivp_at_entry=65.0, gates_passed={"all": True},
    )

    decision = ic.check_position(
        setup,
        now_et=datetime.fromisoformat("2026-08-11T10:00:00-04:00"),
    )

    assert decision["status"] == "blocked"
    assert decision["reason"] == "monitor_spread_quote_unavailable"


def test_monitor_runners_persist_to_strategy_ledgers() -> None:
    root = pm.ROOT
    pm_runner = (root / "scripts" / "run_spy_0dte_pm_monitor.ps1").read_text(encoding="utf-8")
    ic_runner = (root / "scripts" / "run_spy_iron_condor_monitor.ps1").read_text(encoding="utf-8")

    assert "--ledger" in pm_runner
    assert "spy_0dte_pm_ledger.jsonl" in pm_runner
    assert "--ledger" in ic_runner
    assert "spy_iron_condor_ledger.jsonl" in ic_runner


@pytest.mark.parametrize("module", [pm, ic])
def test_monitor_mode_with_missing_state_never_falls_through_to_entry(
    module, monkeypatch, tmp_path
) -> None:
    state_path = tmp_path / "missing-state.json"
    out_path = tmp_path / "decision.json"
    ledger_path = tmp_path / "ledger.jsonl"
    monkeypatch.setattr(
        "sys.argv",
        [
            str(module.__file__),
            "--check",
            "--state", str(state_path),
            "--ledger", str(ledger_path),
            "--out", str(out_path),
        ],
    )

    module.main()

    decision = json.loads(out_path.read_text(encoding="utf-8"))
    assert decision["status"] == "skipped"
    assert decision["reason"] == "no_shadow_state_file"
    assert not state_path.exists()
    assert not ledger_path.exists()


def test_iron_condor_observe_only_records_evidence_without_open_state(
    monkeypatch, tmp_path
) -> None:
    state_path = tmp_path / "state.json"
    out_path = tmp_path / "decision.json"
    ledger_path = tmp_path / "ledger.jsonl"
    setup = SimpleNamespace(status="open_shadow")
    evidence = []
    monkeypatch.setattr(
        ic,
        "build_setup",
        lambda **_kwargs: (setup, ic._decision("eligible", "all_iron_condor_gates_passed")),
    )
    monkeypatch.setattr(ic, "asdict", lambda item: {"status": item.status})
    monkeypatch.setattr(ic, "record_evidence", lambda item: evidence.append(item) or {})
    monkeypatch.setattr(ic, "record_run_observation", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        "sys.argv",
        [
            str(ic.__file__),
            "--observe-only",
            "--state", str(state_path),
            "--ledger", str(ledger_path),
            "--out", str(out_path),
        ],
    )

    ic.main()

    decision = json.loads(out_path.read_text(encoding="utf-8"))
    assert decision["status"] == "blocked"
    assert decision["reason"] == "counterfactual_observation_only"
    assert setup.status == "counterfactual_shadow"
    assert evidence == [setup]
    assert not state_path.exists()
    assert not ledger_path.exists()
