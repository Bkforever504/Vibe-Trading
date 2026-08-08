"""Tests for Phase 1 flip bot entry-quality telemetry and durable-state safety.

All additions are behavior-neutral: no entry/exit decision logic changed.
These tests pin the new telemetry contract so later phases can rely on it.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies import flip_bot as bot


def _setup_fixture() -> dict:
    return {
        "strategy": "bear_trend",
        "symbol": "SPY",
        "entry_price_est": 1.54,
        "spread_cents": 4,
        "orb_direction": "bear",
        "orb_breakout_candle_atr_ratio": 1.25,
        "expected_move_telemetry_status": "observed_at_entry",
        "expected_move_points": 7.25,
        "opening_range_fraction": 0.19,
        "opening_range_bucket": "compressed_under_20pct",
        "expected_move_consumed_fraction": 0.42,
        "breakout_overshoot_fraction": 0.08,
        "signal_snapshot": {
            "score": 9,
            "close": 745.1,
            "vwap": 746.9,
            "ema50": 746.2,
            "vwap_distance_pct": 0.241,
            "reasons": ["below VWAP", "below 50EMA"],
        },
    }


def test_entry_quality_snapshot_measures_slippage_and_carries_signal() -> None:
    now_et = datetime(2026, 7, 7, 9, 47, 12)
    snap = bot._entry_quality_snapshot(_setup_fixture(), 1.60, "broker_fill", now_et=now_et)

    assert snap["entry_minute_et"] == "09:47"
    assert snap["entry_price_est"] == 1.54
    assert snap["filled_price"] == 1.60
    assert snap["fill_price_source"] == "broker_fill"
    assert snap["slippage_per_contract"] == 0.06
    assert snap["slippage_pct"] == 3.9
    assert snap["spread_cents_at_signal"] == 4
    assert snap["orb_direction"] == "bear"
    assert snap["signal_snapshot"]["vwap_distance_pct"] == 0.241
    assert snap["feature_snapshot"]["schema_version"] == 1
    assert snap["feature_snapshot"]["strategy"] == "bear_trend"
    assert snap["feature_snapshot"]["orb_direction"] == "bear"
    assert snap["feature_snapshot"]["orb_breakout_candle_atr_ratio"] == 1.25
    assert snap["feature_snapshot"]["expected_move_telemetry_status"] == "observed_at_entry"
    assert snap["feature_snapshot"]["opening_range_bucket"] == "compressed_under_20pct"
    assert snap["feature_snapshot"]["expected_move_consumed_fraction"] == 0.42


def test_entry_quality_snapshot_handles_missing_estimate() -> None:
    setup = _setup_fixture()
    setup["entry_price_est"] = 0.0
    snap = bot._entry_quality_snapshot(setup, 1.60, "estimate_fallback")

    assert snap["entry_price_est"] is None
    assert snap["slippage_per_contract"] is None
    assert snap["slippage_pct"] is None
    assert snap["fill_price_source"] == "estimate_fallback"


def test_primary_consensus_caution_blocks_only_primary_lane() -> None:
    setup = {"execution_lane": "primary", "strategy": "bull_trend"}
    consensus = {
        "recommendation": "stand_aside",
        "blockers": ["market_force_unclear", "htf_mixed_higher_timeframes", "weak_shadow_pnl_evidence"],
    }

    blocker = bot._primary_consensus_caution_blocker(setup, consensus)

    assert blocker is not None
    assert "market_force_unclear" in blocker

    setup["execution_lane"] = "paper_challenger"
    assert bot._primary_consensus_caution_blocker(setup, consensus) is None


def test_entry_slippage_limit_uses_lower_reference_price() -> None:
    setup = {"entry_price_est": 1.30, "selection_ask": 1.25}

    limit_price = bot._max_entry_limit_price(setup, max_slippage_pct=3.0)

    assert limit_price == 1.29


def test_entry_slippage_blocker_blocks_current_ask_above_limit(monkeypatch) -> None:
    setup = {
        "option_symbol": "SPY260717C00747000",
        "entry_price_est": 1.26,
        "selection_ask": 1.26,
    }
    monkeypatch.setattr(
        bot,
        "_selection_quote_fields",
        lambda _occ: {"selection_ask": 1.32, "quote_age_seconds": 0.5},
    )
    monkeypatch.setattr(bot, "MAX_ENTRY_SLIPPAGE_PCT", 3.0)
    monkeypatch.setattr(bot, "_option_mid", lambda _occ: 1.30)

    blocker = bot._entry_slippage_blocker(setup)

    assert blocker is not None
    assert blocker["reason"] == "entry_slippage_above_limit"
    assert blocker["limit_price"] == 1.30


def test_entry_slippage_blocker_requires_fresh_submit_quote(monkeypatch) -> None:
    setup = {
        "option_symbol": "SPY260717C00747000",
        "entry_price_est": 1.26,
        "selection_ask": 1.26,
    }
    monkeypatch.setattr(bot, "_option_mid", lambda _occ: 1.27)
    monkeypatch.setattr(
        bot,
        "_selection_quote_fields",
        lambda _occ: {"selection_ask": 1.27, "quote_age_seconds": 45.0},
    )

    blocker = bot._entry_slippage_blocker(setup)

    assert blocker is not None
    assert blocker["reason"] == "entry_quote_stale_or_unverifiable"


def test_entry_evidence_gate_blocks_raw_and_stale_orb_but_allows_fresh_retest() -> None:
    raw = {
        "strategy": "0dte",
        "confidence_basis": "raw_orb_shadow_only",
        "orb_entry_pattern": "raw_breakout",
        "orb_retest_status": "awaiting_retest",
    }
    stale = {
        "strategy": "0dte",
        "confidence_basis": "fresh_orb_breakout_retest",
        "orb_entry_pattern": "breakout_retest",
        "orb_retest_status": "retest_stale",
        "orb_retest_age_bars": 17,
    }
    fresh = {
        "strategy": "0dte",
        "confidence_basis": "fresh_orb_breakout_retest",
        "orb_entry_pattern": "breakout_retest",
        "orb_retest_status": "retest_confirmed_fresh",
        "orb_retest_age_bars": 2,
    }

    assert bot._entry_evidence_blocker(raw)["reason"] == "unconfirmed_orb_setup_reached_execution"
    assert bot._entry_evidence_blocker(stale)["reason"] == "fresh_orb_retest_evidence_required"
    assert bot._entry_evidence_blocker(fresh) is None
    assert fresh["entry_evidence_gate"] == "passed_fresh_orb_retest"


def test_entry_evidence_gate_preserves_non_orb_strategies_and_blocks_shadow_records() -> None:
    trend = {"strategy": "bull_trend", "orb_entry_pattern": "fresh_vwap_ema_pullback"}
    shadow = {"strategy": "0dte", "execution_mode": "shadow_only", "live_execution_allowed": False}

    assert bot._entry_evidence_blocker(trend) is None
    assert trend["entry_evidence_gate"] == "passed_non_orb_strategy"
    assert bot._entry_evidence_blocker(shadow)["reason"] == "research_only_setup_reached_execution"


def test_entry_execution_snapshot_records_delay_and_executable_slippage() -> None:
    setup = {
        "selection_ask": 1.00,
        "entry_live_ask_at_submit": 1.05,
        "entry_quote_timestamp_at_submit": "2026-07-20T14:30:00Z",
        "entry_quote_age_seconds_at_submit": 0.4,
        "entry_evidence_gate": "passed_fresh_orb_retest",
        "orb_entry_pattern": "breakout_retest",
        "orb_retest_status": "retest_confirmed_fresh",
        "orb_retest_age_bars": 1,
    }
    fill = {
        "entry_price": 1.06,
        "broker_submitted_at": "2026-07-20T14:30:01Z",
        "broker_filled_at": "2026-07-20T14:30:03.500Z",
    }

    evidence = bot._entry_execution_snapshot(setup, fill, "2026-07-20T14:30:01Z")

    assert evidence["submit_to_fill_seconds"] == 2.5
    assert evidence["fill_vs_signal_ask_pct"] == 6.0
    assert evidence["fill_vs_submit_ask_pct"] == 0.952
    assert evidence["entry_evidence_gate"] == "passed_fresh_orb_retest"


def test_fresh_vwap_ema_pullback_requires_touch_and_confirmation() -> None:
    frame = pd.DataFrame(
        {
            "Open": [100.6, 100.7, 100.8, 100.7, 101.0],
            "High": [100.9, 101.0, 101.1, 100.9, 101.4],
            "Low": [100.4, 100.5, 100.6, 100.04, 100.9],
            "Close": [100.7, 100.8, 100.9, 100.8, 101.3],
            "vwap": [100.0] * 5,
            "ema50": [100.0] * 5,
        }
    )

    assert bot._fresh_vwap_ema_pullback(frame, "bull") is True

    frame.loc[3, "Low"] = 100.5
    assert bot._fresh_vwap_ema_pullback(frame, "bull") is False


def test_trend_orb_context_blocks_extended_move_without_fresh_retest() -> None:
    signal = {"close": 104.0}
    orb = {
        "orb_high": 101.0,
        "orb_low": 100.0,
        "direction": "bull",
        "entry_ready": False,
        "retest_status": "retest_stale",
    }

    blocker = bot._trend_orb_context_blocker("bull", signal, orb)

    assert blocker is not None
    assert blocker["reason"] == "trend_orb_extension_without_fresh_retest"
    assert blocker["orb_extension_fraction"] == 3.0

    orb["entry_ready"] = True
    assert bot._trend_orb_context_blocker("bull", signal, orb) is None


def test_orb_signal_records_breakout_candle_atr_ratio(monkeypatch) -> None:
    bars = pd.DataFrame(
        {
            "High": [101.0] * 9 + [103.0],
            "Low": [100.0] * 9 + [101.0],
            "Close": [100.5] * 9 + [102.5],
        }
    )
    monkeypatch.setattr(bot, "_intraday_bars", lambda _symbol: bars)

    signal = bot._orb_signal("SPY")

    assert signal is not None
    assert signal["direction"] == "bull"
    assert signal["baseline_atr5"] == 1.0
    assert signal["breakout_candle_range"] == 2.0
    assert signal["breakout_candle_atr_ratio"] == 2.0


def _orb_retest_frame(*, trailing_bars: int = 1) -> pd.DataFrame:
    highs = [100.8, 101.0, 100.9, 100.7, 100.85, 102.0, 101.5]
    lows = [99.8, 100.1, 99.7, 99.9, 99.75, 100.85, 100.95]
    closes = [100.3, 100.6, 100.2, 100.4, 100.5, 101.8, 101.3]
    for offset in range(trailing_bars):
        highs.append(101.9 + offset * 0.01)
        lows.append(101.15)
        closes.append(101.6 + offset * 0.01)
    return pd.DataFrame({"High": highs, "Low": lows, "Close": closes})


def test_orb_breakout_retest_requires_later_touch_and_hold(monkeypatch) -> None:
    monkeypatch.setattr(bot, "_intraday_bars", lambda _symbol: _orb_retest_frame())

    signal = bot._orb_breakout_retest_signal("SPY")

    assert signal is not None
    assert signal["direction"] == "bull"
    assert signal["retest_confirmed"] is True
    assert signal["retest_status"] == "retest_confirmed_fresh"
    assert signal["entry_ready"] is True
    assert signal["retest_age_bars"] == 1
    assert signal["orb_breakout_directional_close_location_value"] > 0
    assert signal["orb_dislocation_status"] == "observed_at_breakout"
    assert signal["orb_dislocation_velocity_zscore"] is not None


def test_orb_breakout_retest_rejects_stale_confirmation(monkeypatch) -> None:
    monkeypatch.setattr(bot, "_intraday_bars", lambda _symbol: _orb_retest_frame(trailing_bars=17))

    signal = bot._orb_breakout_retest_signal("SPY")

    assert signal is not None
    assert signal["retest_confirmed"] is True
    assert signal["retest_status"] == "retest_stale"
    assert signal["entry_ready"] is False


def _stub_0dte_advisory_context(monkeypatch) -> None:
    monkeypatch.setattr(bot, "_day_type_snapshot", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(bot, "_gex_wall_blocker", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(bot, "_tick_signal", lambda: {"status": "unavailable"})
    monkeypatch.setattr(bot, "_prior_day_hl_context", lambda *_args, **_kwargs: {"status": "unavailable"})
    monkeypatch.setattr(bot, "_market_internals_signal", lambda: {"status": "unavailable"})
    monkeypatch.setattr(bot, "_max_pain_level", lambda _symbol: None)
    monkeypatch.setattr(bot, "_fetch_vix_term_structure", lambda: {"regime": "unknown"})
    monkeypatch.setattr(bot, "_gex_profile_yf", lambda _symbol: {"status": "unavailable"})


def test_live_orb_path_blocks_until_retest_but_raw_shadow_can_measure(monkeypatch) -> None:
    decisions: list[tuple[str, dict]] = []
    raw_orb = {
        "direction": "bull",
        "range_pct": 0.4,
        "orb_high": 100.4,
        "orb_low": 100.0,
        "close": 100.5,
        "entry_ready": False,
        "retest_status": "awaiting_retest",
    }
    monkeypatch.setattr(bot, "_spot", lambda _symbol: 100.5)
    monkeypatch.setattr(bot, "_prev_close", lambda _symbol: 100.0)
    monkeypatch.setattr(bot, "_orb_breakout_retest_signal", lambda _symbol: raw_orb)
    monkeypatch.setattr(bot, "_strategy_skip", lambda _s, _st, reason, **details: decisions.append((reason, details)))
    monkeypatch.setattr(bot, "_atm_option", lambda *_args: ("SPY260716C00100000", 100.0, 1.0, "2026-07-16"))
    monkeypatch.setattr(bot, "_orb_otm_option", lambda *_args: ("SPY260716C00100000", 100.0, 1.0, "2026-07-16"))
    monkeypatch.setattr(bot, "_option_bid_ask_spread_cents", lambda _symbol: 2)
    monkeypatch.setattr(bot, "_selection_quote_fields", lambda _symbol: {})
    monkeypatch.setattr(bot, "_now_et", lambda: datetime(2026, 7, 15, 9, 45))
    _stub_0dte_advisory_context(monkeypatch)

    assert bot._find_0dte_for_symbol(10_000, "SPY") is None
    assert decisions[0][0] == "orb_retest_not_confirmed"

    shadow_setup = bot._find_0dte_for_symbol(10_000, "SPY", require_orb_retest=False)
    assert shadow_setup is not None
    assert shadow_setup["orb_entry_pattern"] == "raw_breakout"
    assert shadow_setup["confidence"] == 7.5
    assert shadow_setup["confidence_basis"] == "raw_orb_shadow_only"


def test_confirmed_orb_retest_reaches_execution_candidate(monkeypatch) -> None:
    confirmed = {
        "direction": "bear",
        "range_pct": 0.3,
        "orb_high": 100.4,
        "orb_low": 100.0,
        "close": 99.8,
        "entry_ready": True,
        "retest_status": "retest_confirmed_fresh",
        "retest_age_bars": 2,
        "retest_tolerance": 0.05,
        "breakout_at": "2026-07-16T09:36:00-04:00",
        "retest_at": "2026-07-16T09:40:00-04:00",
        "breakout_candle_atr_ratio": 1.8,
        "orb_dislocation_velocity_zscore": 2.4,
        "orb_breakout_close_location_value": -0.7,
        "orb_breakout_directional_close_location_value": 0.7,
        "orb_dislocation_status": "observed_at_breakout",
    }
    monkeypatch.setattr(bot, "_spot", lambda _symbol: 99.8)
    monkeypatch.setattr(bot, "_prev_close", lambda _symbol: 100.0)
    monkeypatch.setattr(bot, "_orb_breakout_retest_signal", lambda _symbol: confirmed)
    monkeypatch.setattr(bot, "_atm_option", lambda *_args: ("SPY260716P00100000", 100.0, 1.0, "2026-07-16"))
    monkeypatch.setattr(bot, "_orb_otm_option", lambda *_args: ("SPY260716P00100000", 100.0, 1.0, "2026-07-16"))
    monkeypatch.setattr(bot, "_option_bid_ask_spread_cents", lambda _symbol: 2)
    monkeypatch.setattr(bot, "_selection_quote_fields", lambda _symbol: {})
    monkeypatch.setattr(bot, "_now_et", lambda: datetime(2026, 7, 15, 9, 45))
    _stub_0dte_advisory_context(monkeypatch)

    setup = bot._find_0dte_for_symbol(10_000, "SPY")

    assert setup is not None
    assert setup["right"] == "PUT"
    assert setup["orb_entry_pattern"] == "breakout_retest"
    assert setup["orb_retest_status"] == "retest_confirmed_fresh"
    assert setup["orb_dislocation_velocity_zscore"] == 2.4
    assert setup["confidence"] == 9.5
    assert setup["confidence_basis"] == "fresh_orb_breakout_retest"
    assert "ORB RETEST BEAR" in setup["catalyst"]


def test_qualifying_gap_candidate_stays_shadow_only_without_orb_confirmation(monkeypatch) -> None:
    monkeypatch.setattr(bot, "_spot", lambda _symbol: 99.0)
    monkeypatch.setattr(bot, "_prev_close", lambda _symbol: 100.0)
    monkeypatch.setattr(bot, "_orb_breakout_retest_signal", lambda _symbol: None)
    monkeypatch.setattr(bot, "_atm_option", lambda *_args: ("SPY260717P00099000", 99.0, 1.0, "2026-07-17"))
    monkeypatch.setattr(bot, "_orb_otm_option", lambda *_args: ("SPY260717P00099000", 99.0, 1.0, "2026-07-17"))
    monkeypatch.setattr(bot, "_option_bid_ask_spread_cents", lambda _symbol: 2)
    monkeypatch.setattr(bot, "_selection_quote_fields", lambda _symbol: {})
    monkeypatch.setattr(bot, "_now_et", lambda: datetime(2026, 7, 17, 9, 45))
    _stub_0dte_advisory_context(monkeypatch)

    setup = bot._find_0dte_for_symbol(10_000, "SPY")

    assert setup is not None
    assert setup["right"] == "PUT"
    assert setup["confidence"] == 7.5
    assert setup["confidence_basis"] == "qualifying_gap_shadow_only"


def test_expected_move_entry_snapshot_uses_same_day_iv(tmp_path, monkeypatch) -> None:
    iv_path = tmp_path / "iv.jsonl"
    iv_path.write_text(
        json.dumps({"date": "2026-07-14", "scans": [{"symbol": "SPY", "atm_iv": 0.16}]}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(bot, "IV_HISTORY_LOG_PATH", iv_path)
    orb = {"orb_high": 100.2, "orb_low": 99.8, "close": 100.4}

    snapshot = bot._expected_move_entry_snapshot("SPY", 100.0, orb, day="2026-07-14")

    assert snapshot["expected_move_telemetry_status"] == "observed_at_entry"
    assert snapshot["opening_range_bucket"] == "balanced_20_to_45pct"
    assert snapshot["expected_move_consumed_fraction"] > 0


def test_expected_move_entry_snapshot_rejects_stale_iv(tmp_path, monkeypatch) -> None:
    iv_path = tmp_path / "iv.jsonl"
    iv_path.write_text(
        json.dumps({"date": "2026-07-13", "scans": [{"symbol": "SPY", "atm_iv": 0.16}]}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(bot, "IV_HISTORY_LOG_PATH", iv_path)

    snapshot = bot._expected_move_entry_snapshot(
        "SPY",
        100.0,
        {"orb_high": 100.2, "orb_low": 99.8, "close": 100.4},
        day="2026-07-14",
    )

    assert snapshot == {"expected_move_telemetry_status": "unavailable"}


def test_premium_level_snapshot_records_context_without_gate_authority(tmp_path) -> None:
    report_path = tmp_path / "premium-levels.json"
    report_path.write_text(
        json.dumps({
            "date": "2026-07-16",
            "feed_provenance": "opra",
            "provenance_qualified": True,
            "symbols": {
                "SPY": {
                    "status": "ok",
                    "trade_history_complete": True,
                    "levels": {
                        "CALL": [
                            {"underlying_level": 753.0, "total_premium_dollars": 58_000_000},
                            {"underlying_level": 752.0, "total_premium_dollars": 52_000_000},
                        ],
                        "PUT": [
                            {"underlying_level": 752.0, "total_premium_dollars": 66_000_000},
                            {"underlying_level": 751.0, "total_premium_dollars": 54_000_000},
                        ],
                    },
                },
            },
        }),
        encoding="utf-8",
    )

    snapshot = bot._premium_level_entry_snapshot(
        "SPY",
        750.9,
        day="2026-07-16",
        path=report_path,
    )

    assert snapshot["premium_level_telemetry_status"] == "observed_opra"
    assert snapshot["premium_level_provenance_qualified"] is True
    assert snapshot["premium_level_dominant_right"] == "PUT"
    assert snapshot["premium_level_nearest_call"] == 752.0
    assert snapshot["premium_level_nearest_put"] == 751.0


def test_premium_level_snapshot_rejects_stale_report(tmp_path) -> None:
    report_path = tmp_path / "premium-levels.json"
    report_path.write_text(json.dumps({"date": "2026-07-15"}), encoding="utf-8")

    assert bot._premium_level_entry_snapshot(
        "SPY", 750.0, day="2026-07-16", path=report_path,
    ) == {"premium_level_telemetry_status": "stale"}


def test_update_pnl_extremes_tracks_mfe_and_mae() -> None:
    trade: dict = {}
    assert bot._update_pnl_extremes(trade, 5.0) is True
    assert trade["best_pnl_pct"] == 5.0
    assert trade["worst_pnl_pct"] == 0.0

    # Better print: best moves, worst stays.
    assert bot._update_pnl_extremes(trade, 22.4) is True
    assert trade["best_pnl_pct"] == 22.4
    assert trade["worst_pnl_pct"] == 0.0

    # Drawdown: worst moves, best stays.
    assert bot._update_pnl_extremes(trade, -18.5) is True
    assert trade["best_pnl_pct"] == 22.4
    assert trade["worst_pnl_pct"] == -18.5

    # No change inside the existing range.
    assert bot._update_pnl_extremes(trade, 1.0) is False


def test_path_telemetry_baseline_starts_at_entry_break_even() -> None:
    baseline = bot._path_telemetry_baseline()

    assert baseline["best_pnl_pct"] == 0.0
    assert baseline["worst_pnl_pct"] == 0.0
    assert baseline["path_telemetry_schema_version"] == 1
    assert baseline["path_telemetry_source"] == "live_entry_baseline"


def test_update_pnl_extremes_uses_break_even_baseline_after_restart() -> None:
    trade: dict = {}

    assert bot._update_pnl_extremes(trade, 80.0) is True

    assert trade["best_pnl_pct"] == 80.0
    assert trade["worst_pnl_pct"] == 0.0


def test_profit_protect_lock_floor_has_explicit_runner_tiers() -> None:
    assert bot._profit_protect_lock_floor(40.0) == 30.0
    assert bot._profit_protect_lock_floor(50.0) == 40.0
    assert bot._profit_protect_lock_floor(60.0) == 50.0
    assert bot._profit_protect_lock_floor(66.0) == 56.0


def test_stamp_exit_writes_complete_exit_record() -> None:
    trade = {"entry_price": 1.54, "contracts": 5, "status": "open"}
    bot._stamp_exit(trade, 1.255, "DATE EXIT")

    assert trade["status"] == "closed"
    assert trade["exit_price"] == 1.255
    assert trade["exit_reason"] == "DATE EXIT"
    assert trade["pnl"] == -142.5
    assert trade["exit_price_source"] == "quote_mid_at_order_submission"
    assert trade["exit_at"].endswith("Z")
    # exit_at parses as an aware-ish ISO timestamp.
    datetime.fromisoformat(trade["exit_at"].replace("Z", "+00:00"))
    assert trade["exit_date"]


def test_stamp_exit_records_broker_order_id() -> None:
    trade = {"entry_price": 1.0, "contracts": 1, "status": "open"}

    bot._stamp_exit(trade, 1.5, "PROFIT PROTECT", "exit-order-1")

    assert trade["exit_order_id"] == "exit-order-1"
    assert trade["exit_price_source"] == "quote_mid_at_order_submission"


def test_flip_bot_default_stop_limits_long_option_loss_to_thirty_percent() -> None:
    assert bot.STOP_MULT == 0.70


def test_flip_save_is_atomic_and_leaves_no_temp_files(tmp_path, monkeypatch) -> None:
    state_file = tmp_path / "flip-trades.json"
    monkeypatch.setattr(bot, "STATE_FILE", state_file)

    bot._save([{"id": "t1", "status": "open"}])

    data = json.loads(state_file.read_text(encoding="utf-8"))
    assert data == [{"id": "t1", "status": "open"}]
    leftovers = [p for p in tmp_path.iterdir() if p.name != "flip-trades.json"]
    assert leftovers == []


def test_get_has_no_mutable_default() -> None:
    import inspect

    sig = inspect.signature(bot._get)
    assert sig.parameters["params"].default is None


def test_today_realized_loss_pct_uses_closed_trade_pnl_only() -> None:
    trades = [
        {"status": "closed", "exit_date": "2026-07-10", "pnl": -300.0},
        {"status": "closed", "exit_date": "2026-07-10", "pnl": 100.0},
        {"status": "open", "entry_date": "2026-07-10", "pnl": -900.0},
        {"status": "closed", "exit_date": "2026-07-09", "pnl": -500.0},
    ]
    assert bot._today_realized_loss_pct(trades, 10_000.0, date(2026, 7, 10)) == 0.02
