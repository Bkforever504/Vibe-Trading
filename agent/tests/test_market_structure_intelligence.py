from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.market_structure_intelligence import (
    APLUS_TIMEFRAME_MATRIX,
    PATTERN_CATALOG,
    _ny_0800_0900_range_context,
    _smt_divergence_context,
    _value_area_reversion_context,
    analyze_market_structure,
    confirmed_swings,
    detect_cisd_universal_model,
)


def _bars(closes: list[float], *, volumes: list[float] | None = None) -> list[dict[str, float | str]]:
    start = datetime(2026, 8, 21, 13, 30, tzinfo=timezone.utc)
    output: list[dict[str, float | str]] = []
    for index, close in enumerate(closes):
        prior = closes[index - 1] if index else close
        open_price = prior
        output.append(
            {
                "t": (start + timedelta(minutes=5 * index)).isoformat().replace("+00:00", "Z"),
                "o": open_price,
                "h": max(open_price, close) + 0.12,
                "l": min(open_price, close) - 0.12,
                "c": close,
                "v": (volumes[index] if volumes else 100_000 + index * 2_000),
            }
        )
    return output


def test_pattern_catalog_covers_simple_intermediate_advanced_and_anti_patterns() -> None:
    complexities = {row["complexity"] for row in PATTERN_CATALOG}
    names = {row["id"] for row in PATTERN_CATALOG}

    assert complexities == {"simple", "intermediate", "advanced", "anti_pattern"}
    assert {
        "trend_pullback",
        "range_break_retest",
        "double_top_bottom",
        "head_and_shoulders",
        "compression_breakout",
        "liquidity_sweep_mss_retest",
        "ict_cisd_universal_model",
        "cbc_strong_flip",
        "session_liquidity_sweep_reclaim",
        "failed_breakout_trap",
        "late_chase_exhaustion",
        "midrange_chop",
    } <= names


def test_machine_readable_aplus_timeframe_matrix_matches_runtime_contract() -> None:
    path = Path(__file__).resolve().parents[2] / "research" / "aplus_timeframe_matrix.json"
    payload = json.loads(path.read_text(encoding="utf-8"))

    runtime = [
        {key: row[key] for key in ("timeframe", "role", "minimum_bars", "required_for_aplus")}
        for row in APLUS_TIMEFRAME_MATRIX
    ]
    documented = [
        {key: row[key] for key in ("timeframe", "role", "minimum_bars", "required_for_aplus")}
        for row in payload["timeframes"]
    ]

    assert documented == runtime
    assert payload["authority"]["execution_enabled"] is False
    assert payload["authority"]["can_submit_orders"] is False
    four_hour = next(row for row in runtime if row["timeframe"] == "4h")
    assert four_hour == {
        "timeframe": "4h",
        "role": "higher_timeframe_bias",
        "minimum_bars": 8,
        "required_for_aplus": False,
    }


def test_level_map_and_clc_contract_expose_where_why_and_next_confirmation() -> None:
    rows = _bars([100.0 + index * 0.08 for index in range(24)])
    daily = _bars([92.0 + index * 0.3 for index in range(30)])
    four_hour = _bars([96.0 + index * 0.5 for index in range(10)])

    result = analyze_market_structure(
        rows,
        quote={"bid": 101.83, "ask": 101.85, "freshness": "live", "spread_bps": 1.97},
        rvol=1.8,
        average_dollar_volume=900_000_000,
        direction_hint="bullish",
        higher_timeframes={"1d": daily, "4h": four_hour},
    )

    levels = {row["id"]: row for row in result["liquidity_level_context"]["levels"]}
    assert {"prior_close", "session_vwap"} <= set(levels)
    assert result["liquidity_level_context"]["dealing_range"]["location"] in {"premium", "discount", "equilibrium"}
    assert "nearest_upside" in result["liquidity_level_context"]
    assert "nearest_downside" in result["liquidity_level_context"]
    clc = result["clc_entry_context"]
    assert clc["context"]["frames"]["4h"] == "bullish"
    assert clc["confirmation"]["true_order_flow"] == "unavailable_without_tick_or_mbo"
    assert len(clc["confirmation"]["sequence"]) == 3
    assert clc["next_required"]
    assert clc["execution_enabled"] is False
    assert clc["can_submit_orders"] is False


def test_equal_relative_liquidity_context_maps_retests_and_sweeps_without_score_weight() -> None:
    rows = _bars([100.0, 101.0, 102.0, 101.0, 100.0, 101.0, 102.01, 101.0, 100.0, 102.6])

    result = analyze_market_structure(
        rows,
        quote={"bid": 102.59, "ask": 102.61, "freshness": "live", "spread_bps": 1.95},
        rvol=1.5,
        average_dollar_volume=500_000_000,
        direction_hint="bullish",
    )
    context = result["equal_relative_liquidity_context"]

    assert context["status"] == "available"
    assert any(level["kind"] == "relative_high" for level in context["levels"])
    relative_high = next(level for level in context["levels"] if level["kind"] == "relative_high")
    assert relative_high["touch_count"] == 2
    assert relative_high["sweep_status"] == "swept"
    assert context["score_effect"] == "context_only_pending_local_validation"
    assert context["source_labels"] == ["completed_5m_ohlcv", "volatility_scaled_equal_level_proxy"]
    assert context["execution_enabled"] is False
    assert context["can_submit_orders"] is False


def test_volume_profile_is_labeled_bar_proxy_and_never_changes_grade() -> None:
    rows = _bars(
        [100.0, 100.1, 100.2, 100.1, 100.2, 100.3, 100.2, 100.4, 100.5, 100.45],
        volumes=[100_000, 120_000, 500_000, 650_000, 700_000, 140_000, 110_000, 100_000, 90_000, 80_000],
    )
    result = analyze_market_structure(
        rows,
        quote={"bid": 100.44, "ask": 100.46, "freshness": "live", "spread_bps": 1.99},
        rvol=1.8,
        average_dollar_volume=900_000_000,
    )

    profile = result["volume_profile_context"]
    assert profile["status"] == "proxy_only"
    assert profile["poc"] is not None
    assert profile["val"] <= profile["poc"] <= profile["vah"]
    assert profile["method"] == "completed_bar_typical_price_volume_histogram_v1"
    assert profile["true_trade_at_price"] is False
    assert profile["score_effect"] == "none_until_tick_validation"
    assert profile["execution_enabled"] is False
    assert profile["can_submit_orders"] is False


def test_smt_divergence_is_a_context_only_paired_index_price_proxy() -> None:
    primary = _bars([100.0, 100.1, 100.2, 100.15, 100.3, 100.25, 100.2, 100.55])
    peer = _bars([200.0, 200.1, 200.2, 200.15, 200.3, 200.25, 200.2, 200.25])
    primary[-1]["h"] = max(float(row["h"]) for row in primary[:-1]) + 0.5
    peer[-1]["h"] = max(float(row["h"]) for row in peer[:-1]) - 0.05

    context = _smt_divergence_context(primary, {"SPY": peer})

    assert context["status"] == "divergence_observed"
    assert context["direction"] == "bearish"
    assert context["peer_symbol"] == "SPY"
    assert context["true_order_flow"] is False
    assert context["score_effect"] == "none_until_local_validation"
    assert context["execution_enabled"] is False
    assert context["can_submit_orders"] is False


def test_smt_divergence_reports_each_peer_and_requires_agreement_for_consensus() -> None:
    primary = _bars([100.0, 100.1, 100.2, 100.15, 100.3, 100.25, 100.2, 100.55])
    agreeing_peer = _bars([200.0, 200.1, 200.2, 200.15, 200.3, 200.25, 200.2, 200.25])
    conflicting_peer = _bars([300.0, 300.1, 300.2, 300.15, 300.3, 300.25, 300.2, 300.55])
    primary[-1]["h"] = max(float(row["h"]) for row in primary[:-1]) + 0.5
    agreeing_peer[-1]["h"] = max(float(row["h"]) for row in agreeing_peer[:-1]) - 0.05
    conflicting_peer[-1]["h"] = max(float(row["h"]) for row in conflicting_peer[:-1]) + 0.5
    conflicting_peer[-1]["l"] = min(float(row["l"]) for row in conflicting_peer[:-1]) - 0.5

    context = _smt_divergence_context(primary, {"SPY": agreeing_peer, "DIA": conflicting_peer})

    assert context["peer_count"] == 2
    assert {row["peer_symbol"] for row in context["peer_results"]} == {"SPY", "DIA"}
    assert context["consensus_status"] == "mixed_peer_evidence"
    assert context["consensus_direction"] == "neutral"
    assert context["score_effect"] == "none_until_local_validation"


def test_value_area_reversion_uses_prior_completed_profile_and_has_zero_grade_weight() -> None:
    rows = _bars(
        [100.0, 100.0, 100.05, 100.0, 100.05, 100.0, 100.05, 100.0, 98.0, 100.1],
        volumes=[500_000, 600_000, 700_000, 650_000, 700_000, 650_000, 600_000, 550_000, 80_000, 120_000],
    )
    rows[-2].update({"o": 98.2, "h": 98.3, "l": 97.8, "c": 98.0})
    rows[-1].update({"o": 98.0, "h": 100.3, "l": 97.9, "c": 100.1})

    context = _value_area_reversion_context(rows)

    assert context["status"] == "confirmed_reclaim"
    assert context["direction"] == "bullish"
    assert context["level_name"] == "VAL"
    assert context["volume_confirmation"] is True
    assert context["reentry_volume"] > context["breakout_volume"]
    assert context["reference_profile_excludes_signal_bar"] is True
    assert context["score_effect"] == "none_until_tick_validation"
    assert context["true_trade_at_price"] is False
    assert context["execution_enabled"] is False
    assert context["can_submit_orders"] is False


def test_value_area_price_reentry_without_volume_confirmation_is_not_a_signal() -> None:
    rows = _bars(
        [100.0, 100.0, 100.05, 100.0, 100.05, 100.0, 100.05, 100.0, 98.0, 100.1],
        volumes=[500_000, 600_000, 700_000, 650_000, 700_000, 650_000, 600_000, 550_000, 180_000, 120_000],
    )
    rows[-2].update({"o": 98.2, "h": 98.3, "l": 97.8, "c": 98.0})
    rows[-1].update({"o": 98.0, "h": 100.3, "l": 97.9, "c": 100.1})

    context = _value_area_reversion_context(rows)

    assert context["status"] == "reclaim_unconfirmed_volume"
    assert context["direction"] == "neutral"
    assert context["volume_confirmation"] is False


def test_cbc_strong_flip_requires_a_completed_two_sided_sweep_and_close_through() -> None:
    rows = _bars([100.0, 100.1, 100.2, 100.15, 100.25, 100.2, 100.3, 99.6])
    rows[-2].update({"o": 100.2, "h": 100.55, "l": 100.05, "c": 100.3})
    rows[-1].update({"o": 100.35, "h": 100.7, "l": 99.4, "c": 99.6, "v": 240_000})

    result = analyze_market_structure(
        rows,
        quote={"bid": 99.59, "ask": 99.61, "freshness": "live", "spread_bps": 2.01},
        rvol=1.8,
        average_dollar_volume=700_000_000,
        direction_hint="bearish",
    )

    flip = next(row for row in result["positive_patterns"] if row["pattern_id"] == "cbc_strong_flip")
    assert flip["direction"] == "bearish"
    assert flip["trigger_state"] == "confirmed"
    assert flip["trigger"] == 100.05
    assert flip["invalidation"] == 100.7
    assert flip["claim_status"] == "mechanical_hypothesis_unvalidated"
    assert flip["execution_enabled"] is False
    assert flip["can_submit_orders"] is False


def test_session_liquidity_map_is_causal_and_sweep_probability_is_unavailable() -> None:
    rows = _bars([100.0, 100.1, 100.2, 100.15, 100.25, 100.3, 100.35, 100.1])
    rows[-1].update({"o": 100.4, "h": 101.25, "l": 99.95, "c": 100.1, "v": 260_000})
    prior_day = _bars([99.0, 100.0, 100.5, 100.8])
    for index, row in enumerate(prior_day):
        row["t"] = (datetime(2026, 8, 20, 14, 30, tzinfo=timezone.utc) + timedelta(hours=index)).isoformat().replace("+00:00", "Z")
    prior_day[-1]["h"] = 101.0
    prior_day[0]["l"] = 98.5

    result = analyze_market_structure(
        rows,
        quote={"bid": 100.09, "ask": 100.11, "freshness": "live", "spread_bps": 2.0},
        rvol=2.0,
        average_dollar_volume=700_000_000,
        direction_hint="bearish",
        higher_timeframes={"60m": prior_day},
    )

    levels = {row["id"]: row for row in result["liquidity_level_context"]["levels"]}
    assert levels["pdh"]["price"] == 101.0
    assert levels["pdl"]["price"] == 98.5
    sweep = next(row for row in result["positive_patterns"] if row["pattern_id"] == "session_liquidity_sweep_reclaim")
    assert sweep["level_id"] == "pdh"
    assert sweep["direction"] == "bearish"
    assert sweep["historical_probability"]["value"] is None
    assert sweep["historical_probability"]["status"] == "unavailable_pending_local_outcomes"
    assert result["liquidity_level_context"]["execution_enabled"] is False
    assert result["liquidity_level_context"]["can_submit_orders"] is False


def test_participation_and_macro_context_are_labeled_non_execution_context() -> None:
    result = analyze_market_structure(
        _bars([100.0, 100.1, 100.05, 100.2, 100.15, 100.35, 100.3, 100.55]),
        quote={"bid": 100.54, "ask": 100.56, "freshness": "live", "spread_bps": 1.99},
        rvol=1.8,
        average_dollar_volume=700_000_000,
    )

    participation = result["participation_context"]
    assert participation["method"] == "ohlcv_participation_curvature_proxy_v1"
    assert participation["true_order_flow"] is False
    assert participation["probability"]["value"] is None
    assert participation["execution_enabled"] is False
    assert participation["can_submit_orders"] is False
    assert result["macro_context"]["status"] == "context_only_unvalidated"
    assert result["macro_context"]["active_window"] == "ny_am_0950_1010"


def test_strat_context_classifies_completed_bars_and_requires_four_frames_for_ftfc() -> None:
    rows = _bars([100.0, 100.2, 100.1, 100.3, 100.25, 100.4, 100.35, 100.6])
    rows[-2].update({"o": 100.2, "h": 100.55, "l": 100.05, "c": 100.35})
    rows[-1].update({"o": 100.35, "h": 100.75, "l": 100.10, "c": 100.60})
    higher = {
        "15m": _bars([100.0, 100.4, 100.8, 101.2]),
        "60m": _bars([99.0, 100.0, 101.0, 102.0]),
        "1d": _bars([95.0, 97.0, 99.0, 103.0]),
    }

    result = analyze_market_structure(
        rows,
        quote={"bid": 100.59, "ask": 100.61, "freshness": "live", "spread_bps": 1.99},
        higher_timeframes=higher,
    )

    context = result["strat_context"]
    assert context["current_scenario"] == "2u"
    assert context["ftfc"]["state"] == "bullish"
    assert context["ftfc"]["strict"] is True
    assert context["ftfc"]["frame_count"] == 4
    assert context["probability"]["value"] is None
    assert context["score_effect"] == "none_until_local_validation"
    assert context["execution_enabled"] is False
    assert context["can_submit_orders"] is False


def test_ny_0800_0900_range_context_tracks_first_sweep_without_accepting_social_probability() -> None:
    start = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)  # 08:00 ET
    rows: list[dict[str, float | str]] = []
    for index in range(18):
        stamp = start + timedelta(minutes=5 * index)
        rows.append({
            "t": stamp.isoformat().replace("+00:00", "Z"),
            "o": 100.0,
            "h": 100.8 if index < 12 else 101.2,
            "l": 99.2 if index < 12 else 99.7,
            "c": 100.1 if index < 12 else 100.4,
            "v": 100_000,
        })

    result = analyze_market_structure(
        rows,
        quote={"bid": 100.39, "ask": 100.41, "freshness": "live", "spread_bps": 2.0},
    )

    context = result["ny_0800_0900_range_context"]
    assert context["status"] == "sweep_observed_waiting_cisd"
    assert context["range"] == {"high": 100.8, "low": 99.2, "bar_count": 12}
    assert context["first_sweep"]["side"] == "buy_side"
    assert context["target"] == 99.2
    assert context["historical_probability"]["value"] is None
    assert context["external_claim_status"] == "excluded_until_independently_reproduced"
    assert context["execution_enabled"] is False
    assert context["can_submit_orders"] is False

    stale_cisd = [{
        "trigger_state": "confirmed",
        "direction": "bearish",
        "model_sequence": {"stages": [{"name": "cisd", "timestamp": "2026-08-21T12:55:00Z"}]},
    }]
    chronology = _ny_0800_0900_range_context(rows, stale_cisd)
    assert chronology["status"] == "sweep_observed_waiting_cisd"
    assert chronology["cisd"]["confirmed"] is False


def _cisd_bullish_fixture(*, confirmed: bool) -> tuple[list[dict[str, float | str]], dict[str, list[dict[str, float | str]]]]:
    rows = _bars([102.0, 101.5, 101.0, 101.1, 101.9, 102.2 if confirmed else 101.95])
    overrides = [
        {"o": 102.0, "h": 102.2, "l": 101.8, "c": 102.0},
        {"o": 102.0, "h": 102.1, "l": 101.4, "c": 101.5},
        {"o": 101.5, "h": 101.6, "l": 100.9, "c": 101.0},
        {"o": 101.0, "h": 101.25, "l": 100.5, "c": 101.1},
        {"o": 101.1, "h": 101.95, "l": 101.0, "c": 101.9},
        {"o": 101.9, "h": 102.3, "l": 101.75, "c": 102.2 if confirmed else 101.95},
    ]
    for row, values in zip(rows, overrides):
        row.update(values)
    htf = _bars([100.5, 101.5, 103.5])
    htf[0].update({"o": 100.0, "h": 101.0, "l": 99.0, "c": 100.5})
    htf[1].update({"o": 100.5, "h": 102.0, "l": 100.0, "c": 101.5})
    htf[2].update({"o": 103.0, "h": 104.0, "l": 102.5, "c": 103.5})
    return rows, {"60m": htf}


def test_cisd_universal_model_requires_ordered_core_and_closed_body_confirmation() -> None:
    rows, higher = _cisd_bullish_fixture(confirmed=True)

    patterns = detect_cisd_universal_model(rows, higher_timeframes=higher)

    model = next(row for row in patterns if row["pattern_id"] == "ict_cisd_universal_model")
    assert model["direction"] == "bullish"
    assert model["trigger_state"] == "confirmed"
    assert model["trigger"] == 102.0
    assert model["invalidation"] == 100.5
    assert model["model_sequence"]["chronology_valid"] is True
    assert [stage["name"] for stage in model["model_sequence"]["stages"]] == [
        "htf_fvg_context",
        "third_candle_range",
        "liquidity_sweep",
        "ifvg",
        "cisd",
    ]
    assert all(stage["status"] == "complete" for stage in model["model_sequence"]["stages"])
    assert model["model_sequence"]["probability_status"] == "unvalidated_pattern_hypothesis"
    assert model["closed_bar_only"] is True
    assert model["execution_enabled"] is False
    assert model["can_submit_orders"] is False


def test_cisd_universal_model_wick_through_anchor_remains_pending() -> None:
    rows, higher = _cisd_bullish_fixture(confirmed=False)

    patterns = detect_cisd_universal_model(rows, higher_timeframes=higher)

    model = next(row for row in patterns if row["pattern_id"] == "ict_cisd_universal_model")
    assert rows[-1]["h"] > model["trigger"]
    assert rows[-1]["c"] < model["trigger"]
    assert model["trigger_state"] == "pending_cisd"
    assert model["model_sequence"]["stages"][-1]["status"] == "pending"
    assert model["model_sequence"]["core_complete"] is False


def test_confirmed_swings_do_not_use_future_bars_before_confirmation() -> None:
    rows = _bars([100.0, 101.0, 103.0, 101.5, 100.8])
    rows[2]["h"] = 103.5

    before_confirmation = confirmed_swings(rows[:4], left=2, right=2)
    after_confirmation = confirmed_swings(rows, left=2, right=2)

    assert not any(row["kind"] == "high" and row["position"] == 2 for row in before_confirmation)
    pivot = next(row for row in after_confirmation if row["kind"] == "high" and row["position"] == 2)
    assert pivot["confirmed_position"] == 4
    assert pivot["causal"] is True


def test_confirmed_breakout_retest_produces_exact_manual_review_plan() -> None:
    closes = [100.0, 100.3, 100.1, 100.5, 100.2, 100.45, 100.25, 100.48, 101.2, 100.55, 100.92]
    volumes = [100_000] * 8 + [260_000, 150_000, 210_000]
    result = analyze_market_structure(
        _bars(closes, volumes=volumes),
        quote={"bid": 100.90, "ask": 100.92, "freshness": "live", "spread_bps": 1.98},
        rvol=1.9,
        average_dollar_volume=900_000_000,
        direction_hint="bullish",
    )

    assert result["best_setup"]["pattern_id"] == "range_break_retest"
    assert result["best_setup"]["trigger_state"] == "confirmed"
    # One confirmed pattern is useful but is not "perfect conditions" without
    # the cross-family confluence required for an A grade.
    assert result["decision"] == "WAIT"
    assert result["score"] == result["pattern_grade"]["final_score"]
    assert result["grade"] == result["pattern_grade"]["grade"]
    assert result["grade"] in {"A", "B", "C", "D"}
    assert result["pattern_grade"]["execution_enabled"] is False
    assert result["pattern_grade"]["can_submit_orders"] is False
    assert result["entry_plan"]["trigger"] is not None
    assert result["entry_plan"]["invalidation"] < result["entry_plan"]["trigger"]
    assert len(result["exit_plan"]["targets"]) == 2
    assert result["exit_plan"]["time_stop_bars"] > 0
    assert result["exit_plan"]["time_stop"] == {
        "bars": 6,
        "timeframe": "5m",
        "minutes": 30,
        "status": "research_default_pending_local_validation",
    }
    assert result["entry_plan"]["timeframe"] == "5m"
    assert result["timeframe_plan"]["primary_trigger"] == "5m"
    assert result["timeframe_plan"]["execution_refinement"] == "1m_optional_not_standalone"
    assert result["execution_enabled"] is False
    assert result["can_submit_orders"] is False


def test_aplus_timeframe_matrix_scans_derived_and_supplied_completed_frames() -> None:
    rows = _bars([100.0 + index * 0.05 for index in range(120)])
    daily = _bars([90.0 + index * 0.4 for index in range(30)])
    weekly = _bars([75.0 + index * 1.0 for index in range(12)])

    result = analyze_market_structure(
        rows,
        quote={"bid": 105.94, "ask": 105.96, "freshness": "live", "spread_bps": 1.89},
        rvol=1.8,
        average_dollar_volume=900_000_000,
        direction_hint="bullish",
        higher_timeframes={"1d": daily, "1w": weekly},
    )

    coverage = {row["timeframe"]: row for row in result["timeframe_coverage"]["frames"]}
    assert result["timeframe_coverage"]["status"] == "complete_for_aplus_review"
    assert result["timeframe_coverage"]["missing_required"] == []
    assert coverage["5m"]["provenance"] == "primary_completed_bars"
    assert coverage["15m"]["provenance"] == "derived_from_completed_5m"
    assert coverage["30m"]["provenance"] == "derived_from_completed_5m"
    assert coverage["60m"]["provenance"] == "derived_from_completed_5m"
    assert coverage["1d"]["provenance"] == "supplied_completed_bars"
    assert coverage["1w"]["required_for_aplus"] is False
    assert {row["timeframe"] for row in result["timeframe_scan"]} >= {"5m", "15m", "30m", "60m", "1d", "1w"}
    assert all(row["execution_enabled"] is False and row["can_submit_orders"] is False for row in result["timeframe_scan"])


def test_missing_daily_regime_context_blocks_aplus_review_without_hiding_setup() -> None:
    rows = _bars([100.0 + index * 0.04 for index in range(120)])

    result = analyze_market_structure(
        rows,
        quote={"bid": 104.74, "ask": 104.76, "freshness": "live", "spread_bps": 1.91},
        rvol=2.0,
        average_dollar_volume=900_000_000,
        direction_hint="bullish",
    )

    assert "1d" in result["timeframe_coverage"]["missing_required"]
    assert "incomplete_aplus_timeframe_coverage" in result["hard_blockers"]
    assert result["decision"] != "READY_TO_REVIEW"


def test_stale_daily_regime_is_reported_and_blocks_aplus_review() -> None:
    rows = _bars([100.0 + index * 0.04 for index in range(120)])
    daily = _bars([90.0 + index * 0.4 for index in range(30)])
    for index, row in enumerate(daily):
        row["t"] = (
            datetime(2026, 7, 1, 20, 0, tzinfo=timezone.utc) + timedelta(days=index)
        ).isoformat().replace("+00:00", "Z")

    result = analyze_market_structure(
        rows,
        quote={"bid": 104.74, "ask": 104.76, "freshness": "live", "spread_bps": 1.91},
        rvol=2.0,
        average_dollar_volume=900_000_000,
        direction_hint="bullish",
        higher_timeframes={"1d": daily},
    )

    coverage = {row["timeframe"]: row for row in result["timeframe_coverage"]["frames"]}
    assert coverage["1d"]["status"] == "required_stale"
    assert coverage["1d"]["lag_minutes_vs_primary"] > coverage["1d"]["max_lag_minutes"]
    assert "1d" in result["timeframe_coverage"]["missing_required"]
    assert "incomplete_aplus_timeframe_coverage" in result["hard_blockers"]


def test_weekly_advisory_context_is_visible_but_does_not_create_intraday_conflict() -> None:
    result = analyze_market_structure(
        _bars([100.0 + index * 0.05 for index in range(120)]),
        quote={"bid": 105.94, "ask": 105.96, "freshness": "live", "spread_bps": 1.89},
        rvol=1.8,
        average_dollar_volume=900_000_000,
        direction_hint="bullish",
        higher_timeframes={
            "1d": _bars([90.0 + index * 0.4 for index in range(30)]),
            "1w": _bars([100.0 - index * 1.0 for index in range(12)]),
        },
    )

    assert result["timeframe_alignment"]["frames"]["1w"]["bias"] == "bearish"
    assert result["timeframe_alignment"]["state"] == "aligned"
    assert "higher_timeframe_conflict" not in result["hard_blockers"]


def test_stale_market_structure_applies_freshness_penalty_and_cannot_be_ready() -> None:
    result = analyze_market_structure(
        _bars([100.0, 100.3, 100.1, 100.5, 100.2, 100.45, 100.25, 100.48, 101.2, 100.55, 100.92]),
        quote={"bid": 100.90, "ask": 100.92, "freshness": "stale", "spread_bps": 1.98},
        rvol=1.9,
        average_dollar_volume=900_000_000,
        direction_hint="bullish",
    )

    assert result["pattern_grade"]["penalty_factors"]["stale_feed"] == 0.5
    assert result["grade"] == "D"
    assert result["decision"] == "REJECT"


def test_failed_breakout_is_named_as_worst_setup_and_rejected() -> None:
    closes = [100.0, 100.25, 100.1, 100.3, 100.15, 100.35, 100.2, 100.32, 101.0, 100.1, 99.85]
    result = analyze_market_structure(
        _bars(closes, volumes=[100_000] * 8 + [230_000, 220_000, 250_000]),
        quote={"bid": 99.84, "ask": 99.86, "freshness": "live", "spread_bps": 2.0},
        rvol=1.7,
        average_dollar_volume=500_000_000,
        direction_hint="bullish",
    )

    assert result["worst_setup"]["pattern_id"] == "failed_breakout_trap"
    assert result["decision"] == "REJECT"
    assert "failed_breakout_against_direction" in result["hard_blockers"]


def test_head_and_shoulders_requires_confirmed_shoulders_and_neckline_break() -> None:
    rows = _bars([100, 101, 103, 101, 99.8, 102, 105, 102, 99.7, 101.5, 103.1, 101, 99.5, 98.8])
    rows[2]["h"], rows[6]["h"], rows[10]["h"] = 103.4, 105.5, 103.35
    rows[4]["l"], rows[8]["l"] = 99.4, 99.35

    result = analyze_market_structure(
        rows,
        quote={"bid": 98.78, "ask": 98.80, "freshness": "live", "spread_bps": 2.02},
        rvol=1.8,
        average_dollar_volume=600_000_000,
        direction_hint="bearish",
    )

    pattern = next(row for row in result["positive_patterns"] if row["pattern_id"] == "head_and_shoulders")
    assert pattern["direction"] == "bearish"
    assert pattern["trigger_state"] == "confirmed"
    assert pattern["closed_bar_only"] is True


def test_liquidity_sweep_requires_reclaim_displacement_and_hold() -> None:
    rows = _bars([100.0, 100.2, 100.1, 100.25, 100.15, 100.0, 100.55, 100.48])
    rows[5].update({"o": 100.1, "h": 100.22, "l": 99.45, "c": 100.0, "v": 240_000})
    rows[6].update({"o": 100.0, "h": 100.68, "l": 99.96, "c": 100.55, "v": 260_000})
    rows[7].update({"o": 100.55, "h": 100.72, "l": 99.92, "c": 100.48, "v": 180_000})

    result = analyze_market_structure(
        rows,
        quote={"bid": 100.47, "ask": 100.49, "freshness": "live", "spread_bps": 1.99},
        rvol=2.0,
        average_dollar_volume=700_000_000,
        direction_hint="bullish",
    )

    assert result["best_setup"]["pattern_id"] == "liquidity_sweep_mss_retest"
    assert result["best_setup"]["trigger_state"] == "confirmed"
    assert result["entry_plan"]["invalidation"] == 99.45


def test_late_chase_and_wide_spread_cannot_be_ready() -> None:
    closes = [100 + index * 0.25 for index in range(18)] + [105.4, 106.3, 107.4]
    result = analyze_market_structure(
        _bars(closes, volumes=[100_000] * 18 + [280_000, 350_000, 480_000]),
        quote={"bid": 107.20, "ask": 107.60, "freshness": "live", "spread_bps": 37.25},
        rvol=3.0,
        average_dollar_volume=700_000_000,
        direction_hint="bullish",
    )

    assert result["decision"] == "REJECT"
    assert result["worst_setup"]["pattern_id"] in {"late_chase_exhaustion", "wide_spread_or_stale"}
    assert "spread_too_wide_or_missing" in result["hard_blockers"]


def test_multi_timeframe_conflict_forces_wait_or_reject() -> None:
    rows = _bars([100.0, 100.3, 100.1, 100.5, 100.2, 100.45, 100.25, 100.48, 101.2, 100.55, 100.92])
    higher = {
        "15m": _bars([106.0, 105.2, 104.4, 103.6, 102.8, 102.0, 101.4]),
        "60m": _bars([112.0, 110.0, 108.0, 106.0, 104.0, 102.0]),
    }
    result = analyze_market_structure(
        rows,
        quote={"bid": 100.90, "ask": 100.92, "freshness": "live", "spread_bps": 1.98},
        rvol=1.8,
        average_dollar_volume=900_000_000,
        direction_hint="bullish",
        higher_timeframes=higher,
    )

    assert result["timeframe_alignment"]["state"] == "conflict"
    assert result["decision"] in {"WAIT", "REJECT"}
    assert "higher_timeframe_conflict" in result["hard_blockers"]


def test_insufficient_bars_fails_closed_with_provenance() -> None:
    result = analyze_market_structure(
        _bars([100.0, 100.2, 100.1]),
        quote={"bid": 100.0, "ask": 100.02, "freshness": "live", "spread_bps": 2.0},
    )

    assert result["decision"] == "STAND_ASIDE"
    assert result["best_setup"] is None
    assert result["freshness"] == "live"
    assert {
        "completed_5m_bars",
        "latest_quote",
        "pattern_grade_v1",
        "ict_cisd_sequence_v1",
        "cbc_strong_flip_v1",
        "session_liquidity_levels_v1",
        "ohlcv_participation_curvature_proxy_v1",
        "completed_ohlcv_strat_scenarios_v1",
        "completed_0800_0900_et_bars",
    } == set(result["source_labels"])
    assert result["execution_enabled"] is False
    assert result["can_submit_orders"] is False
