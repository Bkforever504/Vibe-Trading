from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from strategies import flip_bot


def _ready_context(direction: str = "bull") -> dict:
    return {
        "status": "entry_ready",
        "entry_ready": True,
        "direction": direction,
        "signal_score": 9.0,
        "close": 101.0 if direction == "bull" else 99.0,
        "vwap": 100.4 if direction == "bull" else 99.6,
        "upper_band": 100.5,
        "lower_band": 99.5,
        "noise_fraction": 0.005,
        "structural_stop": 100.5 if direction == "bull" else 99.5,
        "lookback_sessions_observed": 14,
        "current_bars_observed": 31,
        "formula_version": "ssrn_4824172_noise_area_v1",
    }


def _setup(strategy: str = "0dte", *, paper_only: bool = False, contracts: int = 1) -> dict:
    return {
        "strategy": strategy,
        "symbol": "SPY",
        "right": "CALL",
        "option_symbol": "SPY260716C00100000",
        "strike": 100.0,
        "expiry": "2026-07-16",
        "contracts": contracts,
        "entry_price_est": 1.0,
        "confidence": 9.0,
        "spread_cents": 2,
        "catalyst": strategy,
        "hard_close_date": "2026-07-16",
        "hard_close_time": "13:45",
        "paper_only": paper_only,
        "paper_research_lane": strategy if paper_only else None,
    }


def test_noise_area_finder_is_one_contract_paper_only(monkeypatch) -> None:
    monkeypatch.setattr(flip_bot, "PAPER", True)
    monkeypatch.setattr(flip_bot, "NOISE_AREA_PAPER_ENABLED", True)
    monkeypatch.setattr(flip_bot, "_noise_area_context", lambda *_args, **_kwargs: _ready_context("bull"))
    monkeypatch.setattr(
        flip_bot,
        "_atm_option",
        lambda *_args: ("SPY260716C00100000", 100.0, 1.0, "2026-07-16"),
    )
    monkeypatch.setattr(flip_bot, "_option_bid_ask_spread_cents", lambda _symbol: 2)
    monkeypatch.setattr(flip_bot, "_selection_quote_fields", lambda _symbol: {"selection_bid": 0.99, "selection_ask": 1.01})

    setup = flip_bot.find_noise_area_0dte(10_000)

    assert setup is not None
    assert setup["strategy"] == "noise_area_vwap"
    assert setup["right"] == "CALL"
    assert setup["contracts"] == 1
    assert setup["paper_only"] is True
    assert setup["paper_research_lane"] == "noise_area_vwap"
    assert setup["noise_area_formula_version"] == "ssrn_4824172_noise_area_v1"


def test_noise_area_finder_cannot_exist_outside_paper(monkeypatch) -> None:
    monkeypatch.setattr(flip_bot, "PAPER", False)
    monkeypatch.setattr(flip_bot, "NOISE_AREA_PAPER_ENABLED", True)
    monkeypatch.setattr(
        flip_bot,
        "_noise_area_context",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not evaluate")),
    )

    assert flip_bot.find_noise_area_0dte(10_000) is None


def test_recurring_intraday_entry_cannot_run_outside_paper(monkeypatch) -> None:
    decisions = []
    monkeypatch.setattr(flip_bot, "PAPER", False)
    monkeypatch.setattr(flip_bot, "_decision", lambda *args, **kwargs: decisions.append((args, kwargs)))
    monkeypatch.setattr(
        flip_bot,
        "_market_open",
        lambda: (_ for _ in ()).throw(AssertionError("paper boundary must run first")),
    )

    flip_bot.run_entry(10_000, intraday_only=True)

    assert decisions[0][0][3] == "paper_only_intraday_lane"


def _prepare_entry_run(monkeypatch, tmp_path: Path) -> list[dict]:
    submitted: list[dict] = []
    monkeypatch.setattr(flip_bot, "PAPER", True)
    monkeypatch.setattr(flip_bot, "STATE_FILE", tmp_path / "flip-trades.json")
    monkeypatch.setattr(flip_bot, "_market_open", lambda: True)
    monkeypatch.setattr(flip_bot, "_load", lambda: [])
    monkeypatch.setattr(flip_bot, "_fetch_broker_open_symbols", lambda: set())
    monkeypatch.setattr(flip_bot, "_today_realized_loss_pct", lambda *_args, **_kwargs: 0.0)
    monkeypatch.setattr(flip_bot, "shadow_entry_advice", lambda *_args: {"enabled": False})
    monkeypatch.setattr(
        flip_bot,
        "evaluate_execution",
        lambda **_kwargs: SimpleNamespace(allowed=True, reason="", details={}),
    )
    monkeypatch.setattr(
        flip_bot,
        "_submit",
        lambda symbol, qty, side, max_notional=0.0, limit_price=None: submitted.append(
            {
                "symbol": symbol,
                "qty": qty,
                "side": side,
                "max_notional": max_notional,
                "limit_price": limit_price,
            }
        ) or {"id": "paper-order"},
    )
    monkeypatch.setattr(
        flip_bot,
        "_get",
        lambda _path: {"id": "paper-order", "status": "filled", "filled_avg_price": "1.0", "filled_qty": "1"},
    )
    monkeypatch.setattr(flip_bot, "_capture_point_in_time", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        flip_bot,
        "_selection_quote_fields",
        lambda _symbol: {"selection_bid": 0.99, "selection_ask": 1.01},
    )
    monkeypatch.setattr(flip_bot, "_decision", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(flip_bot, "_alert", lambda _message: None)
    monkeypatch.setattr(flip_bot.time, "sleep", lambda _seconds: None)
    return submitted


def test_intraday_entry_prioritizes_orb_over_noise(monkeypatch, tmp_path: Path) -> None:
    submitted = _prepare_entry_run(monkeypatch, tmp_path)
    monkeypatch.setattr(flip_bot, "find_0dte", lambda _account: _setup("0dte"))
    monkeypatch.setattr(
        flip_bot,
        "find_noise_area_0dte",
        lambda _account: (_ for _ in ()).throw(AssertionError("ORB must have priority")),
    )

    flip_bot.run_entry(10_000, intraday_only=True)

    buys = [order for order in submitted if order["side"] == "buy"]
    assert len(buys) == 1
    assert buys[0]["qty"] == 1


def test_intraday_noise_fallback_is_capped_and_labeled(monkeypatch, tmp_path: Path) -> None:
    submitted = _prepare_entry_run(monkeypatch, tmp_path)
    monkeypatch.setattr(flip_bot, "find_0dte", lambda _account: None)
    monkeypatch.setattr(
        flip_bot,
        "find_noise_area_0dte",
        lambda _account: _setup("noise_area_vwap", paper_only=True, contracts=4),
    )

    flip_bot.run_entry(10_000, intraday_only=True)

    buys = [order for order in submitted if order["side"] == "buy"]
    assert len(buys) == 1
    assert buys[0]["qty"] == 1
    saved = (tmp_path / "flip-trades.json").read_text(encoding="utf-8")
    assert '"execution_lane": "paper_research"' in saved
    assert '"paper_only": true' in saved


def test_noise_area_structural_exit_only_applies_to_paper_strategy(monkeypatch) -> None:
    monkeypatch.setattr(flip_bot, "PAPER", True)
    monkeypatch.setattr(
        flip_bot,
        "_noise_area_context",
        lambda *_args, **_kwargs: {
            "close": 100.4,
            "vwap": 100.6,
            "upper_band": 100.5,
            "lower_band": 99.5,
        },
    )

    reason = flip_bot._noise_area_structural_exit_reason(
        {"strategy": "noise_area_vwap", "right": "CALL"}
    )
    assert reason.startswith("NOISE AREA STRUCTURE EXIT")
    assert flip_bot._noise_area_structural_exit_reason({"strategy": "0dte", "right": "CALL"}) == ""


def test_monitor_runner_enables_noise_and_recurring_intraday_scan() -> None:
    runner = (Path(__file__).resolve().parents[2] / "scripts" / "run_flip_bot_monitor.ps1").read_text(encoding="utf-8")

    assert 'FLIP_NOISE_AREA_PAPER_ENABLED = "true"' in runner
    assert "--monitor" in runner
    assert "--intraday-entry" in runner
    assert runner.index("--monitor") < runner.index("--intraday-entry")
