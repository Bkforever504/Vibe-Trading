from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from strategies import flip_bot


ROOT = Path(__file__).resolve().parents[2]


def _setup() -> dict:
    return {
        "strategy": "0dte",
        "symbol": "SPY",
        "right": "CALL",
        "option_symbol": "SPY260810C00650000",
        "strike": 650.0,
        "expiry": "2026-08-10",
        "contracts": 1,
        "entry_price_est": 0.15,
        "entry_limit_price": 0.15,
        "spread_cents": 1,
        "confidence": 9.0,
        "hard_close_time": "14:45",
        "signal_snapshot": {"close": 650.0, "vwap": 649.8},
    }


def _stub_non_ev_gates(monkeypatch, setup: dict) -> None:
    monkeypatch.setattr(flip_bot, "PAPER", True)
    monkeypatch.setattr(flip_bot, "LIVE_EXECUTION_ENABLED", False)
    monkeypatch.setattr(flip_bot, "_market_open", lambda: True)
    monkeypatch.setattr(
        flip_bot,
        "_now_et",
        lambda: datetime(2026, 8, 10, 9, 40, tzinfo=ZoneInfo("America/New_York")),
    )
    monkeypatch.setattr(flip_bot, "find_0dte", lambda _account: dict(setup))
    monkeypatch.setattr(flip_bot, "find_bear_trend_day", lambda _account: None)
    monkeypatch.setattr(flip_bot, "find_bull_trend_day", lambda _account: None)
    monkeypatch.setattr(flip_bot, "find_gap_continuation", lambda _account: [])
    monkeypatch.setattr(
        flip_bot,
        "_execution_authorization",
        lambda _symbol, contracts: {"allowed": True, "contracts": contracts, "lane": "primary"},
    )
    monkeypatch.setattr(flip_bot, "_fetch_broker_open_symbols", lambda: set())
    monkeypatch.setattr(flip_bot, "_same_day_reentry_blocker", lambda *_args: None)
    monkeypatch.setattr(flip_bot, "shadow_entry_advice", lambda *_args, **_kwargs: {"enabled": False})
    monkeypatch.setattr(
        flip_bot,
        "evaluate_execution",
        lambda **_kwargs: type("Decision", (), {"allowed": True})(),
    )
    monkeypatch.setattr(flip_bot, "_entry_slippage_blocker", lambda _setup: None)
    monkeypatch.setattr(flip_bot, "_entry_evidence_blocker", lambda _setup: None)
    monkeypatch.setattr(flip_bot, "_capture_point_in_time", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(flip_bot, "_entry_execution_snapshot", lambda *_args: {})
    monkeypatch.setattr(flip_bot, "_entry_quality_snapshot", lambda *_args: {})
    monkeypatch.setattr(flip_bot, "_alert", lambda _message: None)
    monkeypatch.setattr(flip_bot, "_decision", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(flip_bot.time, "sleep", lambda _seconds: None)


def test_client_order_id_is_deterministic_and_timeout_recovers_existing(monkeypatch) -> None:
    identity = "trade-123"
    assert flip_bot._stable_client_order_id("entry", identity) == flip_bot._stable_client_order_id(
        "entry", identity
    )

    posts = []
    monkeypatch.setattr(
        flip_bot,
        "_post",
        lambda *_args, **_kwargs: posts.append(1)
        or (_ for _ in ()).throw(requests.Timeout("accepted but response lost")),
    )
    monkeypatch.setattr(flip_bot, "_get", lambda _path: {"id": "recovered", "status": "accepted"})
    monkeypatch.setattr(flip_bot, "_alert", lambda _message: None)

    result = flip_bot._submit(
        "SPY260810C00650000",
        1,
        "buy",
        limit_price=0.15,
        client_order_id=flip_bot._stable_client_order_id("entry", identity),
    )

    assert result["id"] == "recovered"
    assert posts == [1]


def test_exploration_blocks_contract_above_account_risk_budget(monkeypatch, tmp_path) -> None:
    state_file = tmp_path / "flip-trades.json"
    state_file.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(flip_bot, "STATE_FILE", state_file)
    setup = _setup()
    setup["entry_price_est"] = 0.25
    setup["entry_limit_price"] = 0.25
    _stub_non_ev_gates(monkeypatch, setup)
    monkeypatch.setattr(flip_bot, "EXPLORATION_MAX_NOTIONAL_DOLLARS", 20.0)
    submitted = []
    monkeypatch.setattr(
        flip_bot,
        "_submit_entry_ladder",
        lambda *_args, **_kwargs: submitted.append(1) or {"id": "must-not-submit"},
    )

    flip_bot.run_exploration_entry(1_000)

    assert submitted == []
    assert json.loads(state_file.read_text(encoding="utf-8")) == []


def test_exploration_uses_monitored_state_and_mirrors_evidence(monkeypatch, tmp_path) -> None:
    state_file = tmp_path / "flip-trades.json"
    state_file.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(flip_bot, "STATE_FILE", state_file)
    _stub_non_ev_gates(monkeypatch, _setup())
    submitted_budgets = []
    monkeypatch.setattr(
        flip_bot,
        "_submit_entry_ladder",
        lambda *_args, **kwargs: submitted_budgets.append(kwargs["max_notional"])
        or {"id": "entry-1", "status": "accepted"},
    )
    monkeypatch.setattr(
        flip_bot,
        "_resolve_entry_fill",
        lambda *_args: {
            "track": True,
            "entry_price": 0.15,
            "entry_price_source": "broker_fill",
            "entry_fill_confirmed": True,
            "contracts": 1,
            "requested_contracts": 1,
            "entry_order_status": "filled",
            "entry_filled_qty": 1,
        },
    )

    def fake_target(trade: dict) -> str:
        trade["resting_tp_order_id"] = "target-1"
        trade["resting_tp_status"] = "new"
        return "submitted"

    monkeypatch.setattr(flip_bot, "_submit_resting_take_profit", fake_target)

    flip_bot.run_exploration_entry(1_000)
    assert submitted_budgets == [100.0]

    authoritative = json.loads(state_file.read_text(encoding="utf-8"))
    mirror = json.loads((tmp_path / "flip-exploration-trades.json").read_text(encoding="utf-8"))
    assert authoritative == mirror
    assert authoritative[0]["execution_lane"] == "exploration"
    assert authoritative[0]["ev_gate_bypassed"] is True
    assert authoritative[0]["resting_tp_order_id"] == "target-1"
    assert authoritative[0]["status"] == "open"


def test_exploration_daily_cap_reads_authoritative_state(monkeypatch, tmp_path) -> None:
    state_file = tmp_path / "flip-trades.json"
    state_file.write_text(
        json.dumps(
            [
                {
                    "id": "existing",
                    "execution_lane": "exploration",
                    "entry_date": "2026-08-10",
                    "status": "closed",
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(flip_bot, "STATE_FILE", state_file)
    monkeypatch.setattr(flip_bot, "PAPER", True)
    monkeypatch.setattr(flip_bot, "LIVE_EXECUTION_ENABLED", False)
    monkeypatch.setattr(flip_bot, "_market_open", lambda: True)
    monkeypatch.setattr(
        flip_bot,
        "_now_et",
        lambda: datetime(2026, 8, 10, 9, 40, tzinfo=ZoneInfo("America/New_York")),
    )
    scans = []
    monkeypatch.setattr(flip_bot, "find_0dte", lambda _account: scans.append(1))

    flip_bot.run_exploration_entry(1_000)

    assert scans == []


def test_exploration_uses_trend_candidate_and_keeps_consensus_advisory(monkeypatch, tmp_path) -> None:
    state_file = tmp_path / "flip-trades.json"
    state_file.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(flip_bot, "STATE_FILE", state_file)
    setup = _setup()
    setup["strategy"] = "bear_trend"
    setup["right"] = "PUT"
    _stub_non_ev_gates(monkeypatch, setup)
    monkeypatch.setattr(flip_bot, "find_0dte", lambda _account: None)
    monkeypatch.setattr(flip_bot, "find_bear_trend_day", lambda _account: dict(setup))
    monkeypatch.setattr(flip_bot, "find_bull_trend_day", lambda _account: None)
    monkeypatch.setattr(
        flip_bot,
        "shadow_entry_advice",
        lambda *_args, **_kwargs: {
            "enabled": True,
            "allowed": True,
            "recommendation": "stand_aside",
            "blockers": ["market_force_unclear", "weak_shadow_pnl_evidence"],
            "hard_blockers": [],
        },
    )
    submitted = []
    monkeypatch.setattr(
        flip_bot,
        "_submit_entry_ladder",
        lambda *_args, **_kwargs: submitted.append(1) or None,
    )

    flip_bot.run_exploration_entry(1_000)

    assert submitted == [1]


def test_exploration_blocks_stacked_consensus_cautions_but_keeps_shadow_evidence(monkeypatch, tmp_path) -> None:
    state_file = tmp_path / "flip-trades.json"
    state_file.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(flip_bot, "STATE_FILE", state_file)
    setup = _setup()
    setup["strategy"] = "bear_trend"
    setup["right"] = "PUT"
    _stub_non_ev_gates(monkeypatch, setup)
    monkeypatch.setattr(flip_bot, "find_0dte", lambda _account: None)
    monkeypatch.setattr(flip_bot, "find_bear_trend_day", lambda _account: dict(setup))
    monkeypatch.setattr(flip_bot, "find_bull_trend_day", lambda _account: None)
    monkeypatch.setattr(
        flip_bot,
        "shadow_entry_advice",
        lambda *_args, **_kwargs: {
            "enabled": True,
            "allowed": True,
            "recommendation": "stand_aside",
            "blockers": [
                "adaptive_stand_aside",
                "htf_intraday_not_aligned",
                "market_force_unclear",
                "weak_shadow_pnl_evidence",
            ],
            "hard_blockers": [],
        },
    )
    decisions = []
    submitted = []
    monkeypatch.setattr(flip_bot, "_decision", lambda *args, **kwargs: decisions.append((args, kwargs)))
    monkeypatch.setattr(
        flip_bot,
        "_submit_entry_ladder",
        lambda *_args, **_kwargs: submitted.append(1) or None,
    )

    flip_bot.run_exploration_entry(1_000)

    assert submitted == []
    assert any(args[3] == "stacked_consensus_stand_aside" for args, _kwargs in decisions)
    blocker = flip_bot._exploration_consensus_caution_blocker({
        "recommendation": "stand_aside",
        "blockers": ["adaptive_stand_aside", "htf_intraday_not_aligned", "market_force_unclear"],
    })
    assert blocker["counterfactual_logging_retained"] is True


def _gap_bars(*, direction: str, benchmark: bool = False) -> pd.DataFrame:
    index = pd.date_range("2026-08-18 09:30", periods=24, freq="min", tz="America/New_York")
    if benchmark:
        closes = [100.0 + position * (0.006 if direction == "bull" else -0.006) for position in range(24)]
        opens = [100.0, *closes[:-1]]
        volume = [1000.0] * 24
    elif direction == "bull":
        closes = [101.10 + position * 0.025 for position in range(18)] + [101.47, 101.43, 101.46, 101.50, 101.55, 101.64]
        opens = [101.0, *closes[:-1]]
        volume = [1000.0] * 18 + [1000.0, 1000.0, 1000.0, 1400.0, 1500.0, 1600.0]
    else:
        closes = [98.90 - position * 0.025 for position in range(18)] + [98.53, 98.57, 98.54, 98.50, 98.45, 98.36]
        opens = [99.0, *closes[:-1]]
        volume = [1000.0] * 18 + [1000.0, 1000.0, 1000.0, 1400.0, 1500.0, 1600.0]
    frame = pd.DataFrame({"Open": opens, "Close": closes, "Volume": volume}, index=index)
    frame["High"] = frame[["Open", "Close"]].max(axis=1) + 0.04
    frame["Low"] = frame[["Open", "Close"]].min(axis=1) - 0.04
    return frame[["Open", "High", "Low", "Close", "Volume"]]


def test_gap_continuation_requires_held_gap_retest_relative_strength_and_volume(monkeypatch) -> None:
    monkeypatch.setattr(flip_bot, "GAP_CONTINUATION_MIN_VOLUME_RATIO", 1.10)
    result = flip_bot._evaluate_gap_continuation(
        _gap_bars(direction="bull"),
        previous_close=100.0,
        benchmark_bars=_gap_bars(direction="bull", benchmark=True),
        symbol="QQQ",
        benchmark_symbol="SPY",
    )

    assert result["eligible"] is True
    assert result["score"] == 10.0
    assert result["right"] == "CALL"
    assert result["execution_enabled"] is False
    assert result["can_submit_orders"] is False


def test_gap_continuation_rejects_full_gap_fill() -> None:
    bars = _gap_bars(direction="bull")
    bars.loc[bars.index[10], "Low"] = 99.95
    result = flip_bot._evaluate_gap_continuation(
        bars,
        previous_close=100.0,
        benchmark_bars=_gap_bars(direction="bull", benchmark=True),
        symbol="QQQ",
        benchmark_symbol="SPY",
    )

    assert result["eligible"] is False
    assert "gap_unfilled" in result["failed_checks"]


def test_gap_continuation_supports_bearish_relative_weakness(monkeypatch) -> None:
    monkeypatch.setattr(flip_bot, "GAP_CONTINUATION_MIN_VOLUME_RATIO", 1.10)
    result = flip_bot._evaluate_gap_continuation(
        _gap_bars(direction="bear"),
        previous_close=100.0,
        benchmark_bars=_gap_bars(direction="bear", benchmark=True),
        symbol="QQQ",
        benchmark_symbol="SPY",
    )

    assert result["eligible"] is True
    assert result["score"] == 10.0
    assert result["right"] == "PUT"


def test_gap_continuation_builder_is_paper_only_and_one_contract(monkeypatch) -> None:
    monkeypatch.setattr(flip_bot, "PAPER", True)
    monkeypatch.setattr(flip_bot, "LIVE_EXECUTION_ENABLED", False)
    monkeypatch.setattr(flip_bot, "GAP_CONTINUATION_PAPER_SYMBOLS", ["QQQ"])
    monkeypatch.setattr(
        flip_bot,
        "_execution_authorization",
        lambda _symbol, _contracts: {"allowed": True, "contracts": 1, "lane": "paper_challenger"},
    )
    monkeypatch.setattr(
        flip_bot,
        "_gap_continuation_context",
        lambda *_args: {
            "eligible": True,
            "score": 10.0,
            "direction": "bear",
            "right": "PUT",
            "gap_pct": -1.4,
            "directional_relative_pct": 0.5,
            "intraday_volume_pace_proxy": 1.4,
        },
    )
    monkeypatch.setattr(
        flip_bot,
        "_select_convex_gap_option",
        lambda *_args: {
            "option_symbol": "QQQ260820P00730000",
            "strike": 730.0,
            "expiry": "2026-08-20",
            "dte": 2,
            "bid": 0.72,
            "ask": 0.75,
            "entry_ask": 0.75,
            "mid": 0.735,
            "delta": -0.52,
            "abs_delta": 0.52,
            "spread_cents": 3,
            "spread_pct": 0.040816,
            "open_interest": 1000,
            "volume": 100,
            "quote_timestamp": "2026-08-18T14:00:00Z",
            "selection_score": 0.9,
            "selection_method": "delta_liquidity_executable_ask_v1",
        },
    )
    monkeypatch.setattr(flip_bot, "_quote_age_seconds", lambda _value: 1.0)
    monkeypatch.setattr(flip_bot, "_decision", lambda *_args, **_kwargs: None)

    setups = flip_bot.find_gap_continuation(1_000)

    assert len(setups) == 1
    assert setups[0]["strategy"] == "gap_continuation"
    assert setups[0]["paper_only"] is True
    assert setups[0]["execution_lane"] == "exploration"
    assert setups[0]["contracts"] == 1
    assert setups[0]["entry_price_est"] == 0.75
    assert setups[0]["contract_selection"]["abs_delta"] == 0.52


def test_convex_option_ranker_rejects_lottery_and_illiquid_contracts(monkeypatch) -> None:
    monkeypatch.setattr(flip_bot, "GAP_OPTION_MIN_DTE", 1)
    monkeypatch.setattr(flip_bot, "GAP_OPTION_MAX_DTE", 7)
    monkeypatch.setattr(flip_bot, "GAP_OPTION_MIN_ABS_DELTA", 0.35)
    monkeypatch.setattr(flip_bot, "GAP_OPTION_MAX_ABS_DELTA", 0.65)
    monkeypatch.setattr(flip_bot, "GAP_OPTION_TARGET_ABS_DELTA", 0.55)
    monkeypatch.setattr(flip_bot, "GAP_OPTION_MAX_SPREAD_PCT", 0.15)
    monkeypatch.setattr(flip_bot, "GAP_OPTION_MIN_OPEN_INTEREST", 100)
    monkeypatch.setattr(flip_bot, "GAP_OPTION_MIN_VOLUME", 10)
    candidates = [
        {"option_symbol": "LOTTERY", "dte": 2, "bid": 0.08, "ask": 0.12, "delta": 0.10, "open_interest": 5000, "volume": 1000},
        {"option_symbol": "WIDE", "dte": 2, "bid": 0.50, "ask": 0.75, "delta": 0.52, "open_interest": 5000, "volume": 1000},
        {"option_symbol": "THIN", "dte": 2, "bid": 1.00, "ask": 1.05, "delta": 0.54, "open_interest": 20, "volume": 2},
        {"option_symbol": "LIQUID", "dte": 2, "bid": 1.00, "ask": 1.05, "delta": 0.54, "open_interest": 1800, "volume": 350},
    ]

    ranked = flip_bot._rank_convex_option_candidates(candidates)

    assert [row["option_symbol"] for row in ranked] == ["LIQUID"]
    assert ranked[0]["entry_ask"] == 1.05
    assert ranked[0]["selection_method"] == "delta_liquidity_executable_ask_v1"


def test_gap_continuation_builder_fails_closed_outside_paper(monkeypatch) -> None:
    monkeypatch.setattr(flip_bot, "PAPER", False)
    assert flip_bot.find_gap_continuation(1_000) == []


def test_exploration_submits_vertical_as_atomic_multileg_order(monkeypatch, tmp_path) -> None:
    state_file = tmp_path / "flip-trades.json"
    state_file.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(flip_bot, "STATE_FILE", state_file)
    setup = _setup()
    setup.update(
        {
            "strategy": "bear_trend_spread",
            "right": "PUT",
            "option_symbol": "SPY260810P00650000",
            "short_option_symbol": "SPY260810P00648000",
            "short_strike": 648.0,
            "entry_price_est": 0.44,
            "entry_limit_price": 0.44,
        }
    )
    _stub_non_ev_gates(monkeypatch, setup)
    monkeypatch.setattr(flip_bot, "find_0dte", lambda _account: None)
    monkeypatch.setattr(flip_bot, "find_bear_trend_day", lambda _account: dict(setup))
    monkeypatch.setattr(
        flip_bot,
        "_hydrate_spread_entry_quote",
        lambda candidate: candidate.update(
            {"spread_cents": 8, "entry_price_est": 0.44, "entry_limit_price": 0.44}
        )
        or {"available": True},
    )
    submitted_spreads = []
    submitted_singles = []
    monkeypatch.setattr(
        flip_bot,
        "_submit_spread",
        lambda candidate, max_notional: submitted_spreads.append((candidate, max_notional)) or None,
    )
    monkeypatch.setattr(
        flip_bot,
        "_submit_entry_ladder",
        lambda *_args, **_kwargs: submitted_singles.append(1) or None,
    )

    flip_bot.run_exploration_entry(1_000)

    assert submitted_singles == []
    assert len(submitted_spreads) == 1
    assert submitted_spreads[0][0]["short_option_symbol"] == "SPY260810P00648000"
    assert submitted_spreads[0][1] == 100.0


def test_spread_entry_quote_uses_executable_two_leg_market(monkeypatch) -> None:
    timestamp = "2026-08-18T14:55:00Z"
    monkeypatch.setattr(
        flip_bot,
        "_option_snapshot_map",
        lambda _symbols: {
            "LONG": {"latestQuote": {"bp": 1.00, "ap": 1.05, "t": timestamp}},
            "SHORT": {"latestQuote": {"bp": 0.61, "ap": 0.64, "t": timestamp}},
        },
    )

    quote = flip_bot._spread_entry_quote_fields("LONG", "SHORT")

    assert quote["available"] is True
    assert quote["selection_bid"] == 0.36
    assert quote["selection_ask"] == 0.44
    assert quote["spread_cents"] == 8


def test_exploration_preserves_hard_consensus_block(monkeypatch, tmp_path) -> None:
    state_file = tmp_path / "flip-trades.json"
    state_file.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(flip_bot, "STATE_FILE", state_file)
    setup = _setup()
    _stub_non_ev_gates(monkeypatch, setup)
    monkeypatch.setattr(
        flip_bot,
        "shadow_entry_advice",
        lambda *_args, **_kwargs: {
            "enabled": True,
            "allowed": False,
            "recommendation": "stand_aside",
            "blockers": ["portfolio_kill_switch_active"],
            "hard_blockers": ["portfolio_kill_switch_active"],
        },
    )
    submitted = []
    monkeypatch.setattr(
        flip_bot,
        "_submit_entry_ladder",
        lambda *_args, **_kwargs: submitted.append(1) or None,
    )

    flip_bot.run_exploration_entry(1_000)

    assert submitted == []


def test_monitor_routes_post_orb_trend_window_to_exploration(monkeypatch) -> None:
    routed = []
    monkeypatch.setattr(flip_bot, "_market_open", lambda: True)
    monkeypatch.setattr(flip_bot, "_load", lambda: [])
    monkeypatch.setattr(flip_bot, "_serialized_monitor_pass", lambda: False)
    monkeypatch.setattr(flip_bot, "ACCELERATED_SHADOW_LEARNING", False)
    monkeypatch.setattr(
        flip_bot,
        "_now_et",
        lambda: datetime(2026, 8, 18, 10, 45, tzinfo=ZoneInfo("America/New_York")),
    )
    monkeypatch.setattr(flip_bot, "resolve_account_size", lambda **_kwargs: 1_000.0)
    monkeypatch.setattr(
        flip_bot,
        "run_exploration_entry",
        lambda account: routed.append(account),
    )

    flip_bot.run_monitor()

    assert routed == [1_000.0]


def test_monitor_routes_empty_primary_slot_to_exploration_during_gap_window(monkeypatch) -> None:
    routed = []
    monkeypatch.setattr(flip_bot, "_market_open", lambda: True)
    monkeypatch.setattr(flip_bot, "_load", lambda: [])
    monkeypatch.setattr(flip_bot, "_serialized_monitor_pass", lambda: False)
    monkeypatch.setattr(flip_bot, "ACCELERATED_SHADOW_LEARNING", False)
    monkeypatch.setattr(
        flip_bot,
        "_now_et",
        lambda: datetime(2026, 8, 18, 10, 0, tzinfo=ZoneInfo("America/New_York")),
    )
    monkeypatch.setattr(flip_bot, "resolve_account_size", lambda **_kwargs: 1_000.0)
    monkeypatch.setattr(
        flip_bot,
        "run_entry",
        lambda account, intraday_only: routed.append(("primary", account, intraday_only)),
    )
    monkeypatch.setattr(
        flip_bot,
        "run_exploration_entry",
        lambda account: routed.append(("exploration", account)),
    )

    flip_bot.run_monitor()

    assert routed == [
        ("primary", 1_000.0, True),
        ("exploration", 1_000.0),
    ]


def test_exploration_router_uses_prior_date_evidence_only(tmp_path) -> None:
    log_path = tmp_path / "daily-universe.jsonl"
    rows = [
        {
            "date": "2026-08-09",
            "rankings": [
                {
                    "symbol": "SPY",
                    "tier": "execution_benchmark",
                    "rank_score": 70,
                    "out_of_sample_positive": True,
                    "shadow_completed_count": 90,
                },
                {
                    "symbol": "QQQ",
                    "tier": "promotion_review",
                    "rank_score": 82,
                    "out_of_sample_positive": True,
                    "out_of_sample_expectancy_return_pct": 5.04,
                    "shadow_completed_count": 112,
                },
            ],
        },
        {
            "date": "2026-08-10",
            "rankings": [
                {
                    "symbol": "SPY",
                    "tier": "promotion_review",
                    "rank_score": 99,
                    "out_of_sample_positive": True,
                    "shadow_completed_count": 999,
                },
                {"symbol": "QQQ", "tier": "blocked", "rank_score": 0},
            ],
        },
    ]
    log_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    selected = flip_bot._select_exploration_candidate(
        [{"symbol": "SPY", "strategy": "0dte"}, {"symbol": "QQQ", "strategy": "0dte"}],
        universe_log_path=log_path,
        today=datetime(2026, 8, 10).date(),
    )

    assert selected["symbol"] == "QQQ"
    assert selected["exploration_routing"]["evidence_report_date"] == "2026-08-09"
    assert selected["exploration_routing"]["evidence_cutoff"] == "strictly_prior_trading_date"
    assert selected["exploration_routing"]["can_enable_live_execution"] is False


def test_exploration_router_falls_back_to_stable_candidate_order(tmp_path) -> None:
    selected = flip_bot._select_exploration_candidate(
        [{"symbol": "SPY"}, {"symbol": "QQQ"}],
        universe_log_path=tmp_path / "missing.jsonl",
        today=datetime(2026, 8, 10).date(),
    )

    assert selected["symbol"] == "SPY"
    assert selected["exploration_routing"]["evidence_report_date"] is None


def test_exploration_router_drops_explicit_shadow_only_candidate(tmp_path) -> None:
    selected = flip_bot._select_exploration_candidate(
        [
            {
                "symbol": "QQQ",
                "strategy": "0dte",
                "confidence": 10.0,
                "confidence_basis": "qualifying_gap_shadow_only",
            },
            {
                "symbol": "SPY",
                "strategy": "gap_continuation",
                "confidence": 10.0,
            },
        ],
        universe_log_path=tmp_path / "missing.jsonl",
    )

    assert selected["symbol"] == "SPY"
    assert selected["strategy"] == "gap_continuation"


def test_exploration_router_prefers_stronger_same_symbol_signal(tmp_path) -> None:
    selected = flip_bot._select_exploration_candidate(
        [
            {"symbol": "SPY", "strategy": "0dte", "confidence": 7.0, "spread_cents": 4},
            {"symbol": "SPY", "strategy": "bear_trend", "confidence": 9.0, "spread_cents": 5},
        ],
        universe_log_path=tmp_path / "missing.jsonl",
        today=datetime(2026, 8, 10).date(),
    )

    assert selected["strategy"] == "bear_trend"
    assert selected["exploration_routing"]["candidate_strategies"] == ["0dte", "bear_trend"]


def test_exploration_router_applies_only_stock_screen_liquidity_veto(tmp_path) -> None:
    log_path = tmp_path / "universe.jsonl"
    report = {
        "date": "2026-08-09",
        "rankings": [
            {"symbol": "SPY", "tier": "execution_benchmark", "rank_score": 50},
            {
                "symbol": "QQQ", "tier": "shadow_challenger", "rank_score": 90,
                "stock_screen_checked": True, "stock_screen_veto": True,
                "stock_screen_long_eligible": True,
            },
        ],
    }
    log_path.write_text(json.dumps(report) + "\n", encoding="utf-8")
    selected = flip_bot._select_exploration_candidate(
        [
            {"symbol": "QQQ", "right": "CALL", "confidence": 10.0},
            {"symbol": "SPY", "right": "CALL", "confidence": 5.0},
        ],
        universe_log_path=log_path,
        today=datetime(2026, 8, 10).date(),
    )
    assert selected["symbol"] == "SPY"


def test_exploration_router_keeps_directional_screen_advisory(tmp_path) -> None:
    log_path = tmp_path / "universe.jsonl"
    report = {
        "date": "2026-08-09",
        "rankings": [{
            "symbol": "QQQ", "tier": "promotion_review", "rank_score": 90,
            "stock_screen_checked": True, "stock_screen_veto": False,
            "stock_screen_long_eligible": False, "stock_screen_short_eligible": True,
            "stock_screen_status": "qualified_short",
        }],
    }
    log_path.write_text(json.dumps(report) + "\n", encoding="utf-8")
    selected = flip_bot._select_exploration_candidate(
        [{"symbol": "QQQ", "right": "CALL", "confidence": 10.0}],
        universe_log_path=log_path,
        today=datetime(2026, 8, 10).date(),
    )
    assert selected["symbol"] == "QQQ"
    assert selected["exploration_routing"]["stock_screen_directional_authority"] == "blocked_failed_1d_5d_20d_walk_forward"


def test_exploration_launcher_keeps_global_ev_gate_enabled() -> None:
    launcher = (ROOT / "scripts" / "run_flip_bot_exploration.ps1").read_text(encoding="utf-8")
    registration = (ROOT / "scripts" / "register_flip_exploration_task.ps1").read_text(
        encoding="utf-8"
    )

    assert '$env:FLIP_EXECUTABLE_EV_GATE_ENABLED = "true"' in launcher
    assert '$env:FLIP_EXECUTABLE_EV_GATE_ENABLED = "false"' not in launcher
    assert '$env:FLIP_MAX_CONTRACTS = "1"' in launcher
    assert '$env:FLIP_MAX_OPEN_POSITIONS = "1"' in launcher
    assert '$env:FLIP_MAX_RISK_PCT = "0.10"' in launcher
    assert '$env:FLIP_EXPLORATION_MAX_NOTIONAL_DOLLARS = "100"' in launcher
    assert '$env:FLIP_GAP_CONTINUATION_PAPER_SYMBOLS = "SPY,QQQ,AAPL,MSFT,NVDA,TSLA,META,AMZN,SMCI"' in launcher
    assert "python scripts\\daily_stock_screener.py" in launcher
    assert "python scripts\\daily_options_universe_ranker.py" in launcher
    assert "-WakeToRun" in registration
    assert '"12:20PM"' in registration
