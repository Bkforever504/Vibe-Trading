from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.daily_move_coverage_review import build_review
from scripts.intraday_opportunity_radar import (
    apply_cross_sectional_factor_consensus,
    apply_market_context,
    bar_features,
    build_report as build_intraday_report,
    coverage_trace,
    discovery_map,
    evaluate_candidate,
    fetch_intraday_bars,
    nominate_symbols,
    rank_candidates_by_lane,
    select_symbols_for_intraday_bars,
    symbols_from_report_payload,
)
from scripts.live_trading_cockpit import build_cockpit


NOW_ET = datetime(2026, 8, 20, 11, 0, tzinfo=ZoneInfo("America/New_York"))


def _bars() -> list[dict]:
    return [
        {"o": 10.0, "h": 10.4, "l": 9.9, "c": 10.3, "v": 500_000},
        {"o": 10.3, "h": 10.6, "l": 10.2, "c": 10.5, "v": 450_000},
        {"o": 10.5, "h": 10.7, "l": 10.4, "c": 10.6, "v": 400_000},
        {"o": 10.6, "h": 11.1, "l": 10.6, "c": 11.0, "v": 900_000},
    ]


def test_discovery_map_admits_unknown_symbol_from_multiple_marketwide_sources() -> None:
    mapped = discovery_map(
        {
            "movers_gainers": [{"symbol": "NEWX", "percent_change": 18.0}],
            "most_active_volume": [{"symbol": "NEWX", "volume": 8_000_000}],
        }
    )

    assert mapped["NEWX"]["sources"] == ["movers_gainers", "most_active_volume"]
    assert mapped["NEWX"]["source_ranks"] == {"movers_gainers": 1, "most_active_volume": 1}


def test_nomination_adds_hut_even_when_market_screeners_miss_it() -> None:
    discovered: dict[str, dict] = {}

    nominate_symbols(discovered, ["HUT", "hut", "bad-symbol"], "known_liquid_leader")
    nominate_symbols(discovered, ["HUT"], "fresh_market_news")

    assert discovered["HUT"]["sources"] == ["known_liquid_leader", "fresh_market_news"]
    assert "BAD-SYMBOL" not in discovered


def test_report_nominees_must_be_from_current_day() -> None:
    current = {"date": "2026-08-20", "scans": [{"symbol": "HUT"}, {"symbol": "CF"}]}
    stale = {"date": "2026-08-19", "scans": [{"symbol": "OLD"}]}

    assert symbols_from_report_payload(current, ("scans",), "2026-08-20") == ["HUT", "CF"]
    assert symbols_from_report_payload(stale, ("scans",), "2026-08-20") == []


def test_coverage_trace_explains_where_a_symbol_stopped() -> None:
    discovered = {
        symbol: {"symbol": symbol, "sources": ["test"], "source_ranks": {}, "screener_values": {}}
        for symbol in ("HUT", "CF", "AU")
    }

    rows = coverage_trace(discovered, {"HUT": {}, "CF": {}}, ["HUT"], {"HUT": _bars()})
    stages = {row["symbol"]: row["stop_stage"] for row in rows}

    assert stages == {
        "AU": "snapshot_unavailable",
        "CF": "not_selected_for_intraday_bars",
        "HUT": "evaluated",
    }


def test_bar_selection_reserves_capacity_for_liquid_thematic_names() -> None:
    discovered = {
        f"X{index}": {"symbol": f"X{index}", "sources": ["fresh_market_news"]}
        for index in range(20)
    }
    metrics = {
        symbol: {"gap_return": 0.50 - index / 100, "snapshot_volume": 1_000 + index}
        for index, symbol in enumerate(discovered)
    }
    discovered["HUT"] = {"symbol": "HUT", "sources": ["known_liquid_leader"]}
    metrics["HUT"] = {"gap_return": 0.055, "snapshot_volume": 200_000}

    selected = select_symbols_for_intraday_bars(discovered, metrics, limit=10)

    assert "HUT" in selected


def test_bar_selection_always_reserves_core_benchmarks() -> None:
    discovered = {
        f"X{index}": {"symbol": f"X{index}", "sources": ["movers_gainers"]}
        for index in range(25)
    }
    metrics = {
        symbol: {"gap_return": 0.50 - index / 100, "snapshot_volume": 1_000_000 - index}
        for index, symbol in enumerate(discovered)
    }
    for symbol in ("SPY", "QQQ", "IWM"):
        discovered[symbol] = {"symbol": symbol, "sources": ["known_liquid_leader"]}
        metrics[symbol] = {"gap_return": 0.0, "snapshot_volume": 1.0}

    selected = select_symbols_for_intraday_bars(discovered, metrics, limit=10)

    assert selected[:3] == ["SPY", "QQQ", "IWM"]
    assert len(selected) == 10


def test_bar_selection_reserves_liquid_mega_caps_before_ranked_quotas() -> None:
    discovered = {
        f"X{index}": {"symbol": f"X{index}", "sources": ["movers_gainers"]}
        for index in range(30)
    }
    metrics = {
        symbol: {"gap_return": 0.50 - index / 100, "snapshot_volume": 1_000_000 - index}
        for index, symbol in enumerate(discovered)
    }
    for symbol in ("SPY", "QQQ", "IWM", "META", "AMZN", "GOOGL", "AMD"):
        discovered[symbol] = {"symbol": symbol, "sources": ["known_liquid_leader"]}
        metrics[symbol] = {"gap_return": 0.0, "snapshot_volume": 1.0}

    selected = select_symbols_for_intraday_bars(discovered, metrics, limit=12)

    assert set(("SPY", "QQQ", "IWM", "META", "AMZN", "GOOGL", "AMD")) <= set(selected)


def test_bar_selection_reserves_official_movers_before_general_activity() -> None:
    discovered = {
        symbol: {"symbol": symbol, "sources": ["movers_gainers"], "source_ranks": {"movers_gainers": rank}}
        for rank, symbol in enumerate(("M1", "M2", "M3", "M4", "M5"), start=1)
    }
    discovered.update({
        symbol: {"symbol": symbol, "sources": ["known_liquid_leader"], "source_ranks": {}}
        for symbol in ("SPY", "QQQ", "IWM")
    })
    discovered.update({
        f"A{index}": {"symbol": f"A{index}", "sources": ["most_active_volume"], "source_ranks": {"most_active_volume": index}}
        for index in range(10)
    })
    metrics = {symbol: {"gap_return": 0.001, "snapshot_volume": 1_000_000} for symbol in discovered}

    selected = select_symbols_for_intraday_bars(discovered, metrics, limit=8)

    assert selected[:3] == ["SPY", "QQQ", "IWM"]
    assert set(("M1", "M2", "M3", "M4", "M5")) <= set(selected)


def test_sector_and_qqq_spy_context_adjust_rank_without_becoming_a_gate() -> None:
    candidates = [
        {"symbol": "AAPL", "direction": "bullish", "ranking_score": 90.0, "hard_gates": {"existing": True}},
        {"symbol": "AAPL", "direction": "bearish", "ranking_score": 90.0, "hard_gates": {"existing": True}},
    ]
    metrics = {
        "SPY": {"gap_return": 0.010},
        "QQQ": {"gap_return": 0.022},
        "XLK": {"gap_return": 0.018},
        "AAPL": {"gap_return": 0.030},
        "XLF": {"gap_return": 0.002},
    }

    enriched = apply_market_context(candidates, metrics)

    long_context = enriched[0]["market_context"]
    short_context = enriched[1]["market_context"]
    assert long_context["sector"] == "tech"
    assert long_context["sector_etf"] == "XLK"
    assert long_context["sector_alignment"] == "supportive"
    assert long_context["qqq_spy_regime"] == "qqq_leading_spy"
    assert enriched[0]["ranking_score"] == 94.0
    assert short_context["sector_alignment"] == "conflicting"
    assert enriched[1]["ranking_score"] == 86.0
    assert enriched[0]["hard_gates"] == {"existing": True}


def test_missing_market_context_is_visible_but_never_penalizes_or_blocks() -> None:
    candidate = {"symbol": "UNKNOWN", "direction": "bullish", "ranking_score": 77.0, "hard_gates": {"existing": True}}

    enriched = apply_market_context([candidate], {"UNKNOWN": {"gap_return": 0.04}})

    assert enriched[0]["ranking_score"] == 77.0
    assert enriched[0]["market_context"]["status"] == "unavailable"
    assert enriched[0]["market_context"]["ranking_adjustment"] == 0.0
    assert enriched[0]["hard_gates"] == {"existing": True}


def test_intraday_bar_fetch_batches_without_silent_symbol_truncation(monkeypatch) -> None:
    calls: list[list[str]] = []

    class Response:
        def __init__(self, symbols: list[str]) -> None:
            self.symbols = symbols

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"bars": {symbol: [{"o": 1, "h": 1, "l": 1, "c": 1, "v": 1}] for symbol in self.symbols}}

    def fake_get(_url, **kwargs):
        symbols = str(kwargs["params"]["symbols"]).split(",")
        calls.append(symbols)
        return Response(symbols)

    monkeypatch.setattr("scripts.intraday_opportunity_radar.requests.get", fake_get)
    symbols = [f"S{index}" for index in range(205)]

    bars, errors = fetch_intraday_bars(symbols, NOW_ET)

    assert errors == []
    assert len(calls) == 3
    assert max(map(len, calls)) <= 100
    assert set(bars) == set(symbols)


def test_intraday_bar_fetch_excludes_currently_forming_five_minute_bar(monkeypatch) -> None:
    requested_ends: list[str] = []

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"bars": {}}

    def fake_get(_url, **kwargs):
        requested_ends.append(str(kwargs["params"]["end"]))
        return Response()

    monkeypatch.setattr("scripts.intraday_opportunity_radar.requests.get", fake_get)

    fetch_intraday_bars(["QQQ"], datetime(2026, 8, 20, 11, 3, tzinfo=ZoneInfo("America/New_York")))

    requested_end = datetime.fromisoformat(requested_ends[0].replace("Z", "+00:00"))
    assert requested_end.astimezone(ZoneInfo("America/New_York")).strftime("%H:%M") == "11:00"


def test_completed_bar_failed_opening_range_breakout_is_bearish_reversal() -> None:
    rows = [
        {"t": "2026-08-20T13:30:00Z", "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.5, "v": 1000},
        {"t": "2026-08-20T13:35:00Z", "o": 100.5, "h": 100.8, "l": 99.8, "c": 100.2, "v": 1000},
        {"t": "2026-08-20T13:40:00Z", "o": 100.2, "h": 100.7, "l": 99.9, "c": 100.4, "v": 1000},
        {"t": "2026-08-20T13:45:00Z", "o": 101.2, "h": 102.0, "l": 100.0, "c": 100.5, "v": 1200},
    ]

    features = bar_features(rows)

    assert features["price_action_state"] == "bearish_confirmed"
    assert features["price_action_pattern"] == "failed_opening_range_breakout"
    assert features["primary_reversal"]["observed_at"] == rows[-1]["t"]
    assert features["primary_reversal"]["bar_basis"] == "completed_5m_only"
    assert features["primary_reversal"]["can_submit_orders"] is False

    candidate = evaluate_candidate(
        {"symbol": "QQQ", "sources": ["known_liquid_leader", "most_active_volume"], "source_ranks": {}},
        {"price": 100.5, "gap_return": 0.004, "spread_pct": 0.001, "snapshot_volume": 9_000_000},
        features,
        500_000_000,
        [],
        NOW_ET,
    )
    assert candidate["direction"] == "bearish"
    assert candidate["setup"] == "failed_opening_range_breakout"
    assert candidate["factor_scores"]["structure"] == 96.0
    assert candidate["ranking_score"] >= candidate["score"] + 12.0
    assert candidate["can_submit_orders"] is False


def test_completed_bar_sweep_reclaim_and_vwap_reclaim_are_mechanical_observations() -> None:
    sweep_rows = [
        {"t": "1", "o": 100.0, "h": 101.0, "l": 98.0, "c": 100.0, "v": 1000},
        {"t": "2", "o": 100.0, "h": 100.8, "l": 99.2, "c": 100.1, "v": 1000},
        {"t": "3", "o": 100.1, "h": 100.7, "l": 99.1, "c": 100.0, "v": 1000},
        {"t": "4", "o": 100.0, "h": 100.5, "l": 99.0, "c": 99.4, "v": 1000},
        {"t": "5", "o": 99.1, "h": 100.2, "l": 98.8, "c": 99.8, "v": 1200},
    ]
    vwap_rows = [
        {"t": "1", "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.4, "v": 1000},
        {"t": "2", "o": 100.4, "h": 100.8, "l": 99.4, "c": 100.2, "v": 1000},
        {"t": "3", "o": 100.2, "h": 100.7, "l": 99.3, "c": 99.8, "v": 1000},
        {"t": "4", "o": 99.9, "h": 100.7, "l": 99.5, "c": 100.5, "v": 1200},
    ]

    sweep = bar_features(sweep_rows)
    reclaim = bar_features(vwap_rows)

    assert "sweep_and_reclaim" in {row["pattern"] for row in sweep["reversal_observations"]}
    assert reclaim["price_action_pattern"] == "vwap_reclaim"
    assert reclaim["confirmation_trigger"] == 100.7


def test_benchmark_lane_ranks_only_benchmarks_and_ignores_penny_competition() -> None:
    rows = [
        {"symbol": "PENNY", "ranking_score": 99, "change_pct": 80, "confirmation_stage": "completed_5m_confirmed", "factor_consensus": {"score": 99}},
        {"symbol": "QQQ", "ranking_score": 75, "change_pct": 0.7, "confirmation_stage": "completed_5m_confirmed", "factor_consensus": {"score": 1}},
        {"symbol": "SPY", "ranking_score": 68, "change_pct": 0.4, "confirmation_stage": "awaiting_completed_5m_confirmation", "factor_consensus": {"score": 2}},
        {"symbol": "IWM", "ranking_score": 72, "change_pct": 0.5, "confirmation_stage": "completed_5m_confirmed", "factor_consensus": {"score": 3}},
    ]

    enriched, benchmarks, broad = rank_candidates_by_lane(rows)

    assert [row["symbol"] for row in benchmarks] == ["QQQ", "IWM", "SPY"]
    assert [row["lane_rank"] for row in benchmarks] == [1, 2, 3]
    assert broad[0]["symbol"] == "PENNY"
    assert broad[0]["ranking_lane"] == "broad_mover"
    assert {row["ranking_lane"] for row in enriched if row["symbol"] in {"SPY", "QQQ", "IWM"}} == {"benchmark"}


def test_report_exposes_benchmark_lane_schema(monkeypatch) -> None:
    screeners = {
        "movers_gainers": [{"symbol": "PENNY", "percent_change": 80}],
        "movers_losers": [],
        "most_active_volume": [],
        "most_active_trades": [],
    }
    symbols = ["SPY", "QQQ", "IWM", "PENNY"]
    metrics = {
        symbol: {"price": 100.0, "gap_return": 0.01, "spread_pct": 0.001, "snapshot_volume": 1_000_000}
        for symbol in symbols
    }
    monkeypatch.setattr("scripts.intraday_opportunity_radar.fetch_market_screeners", lambda: (screeners, []))
    monkeypatch.setattr("scripts.intraday_opportunity_radar.fetch_news", lambda *_args, **_kwargs: ([], []))
    monkeypatch.setattr("scripts.intraday_opportunity_radar.load_social_symbols", lambda *_args: [])
    monkeypatch.setattr("scripts.intraday_opportunity_radar._read_json", lambda *_args: {})
    monkeypatch.setattr("scripts.intraday_opportunity_radar.fetch_snapshots", lambda *_args: ({symbol: metrics[symbol] for symbol in symbols}, []))
    monkeypatch.setattr("scripts.intraday_opportunity_radar.snapshot_metrics", lambda snapshot: snapshot)
    monkeypatch.setattr("scripts.intraday_opportunity_radar.select_symbols_for_intraday_bars", lambda *_args, **_kwargs: symbols)
    monkeypatch.setattr("scripts.intraday_opportunity_radar.fetch_intraday_bars", lambda *_args: ({symbol: _bars() for symbol in symbols}, []))
    monkeypatch.setattr("scripts.intraday_opportunity_radar.fetch_daily_liquidity", lambda *_args: ({symbol: 500_000_000 for symbol in symbols}, []))

    report = build_intraday_report(NOW_ET)

    lane = report["benchmark_lane"]
    assert lane["symbols"] == ["SPY", "QQQ", "IWM"]
    assert lane["counts"]["configured"] == 3
    assert lane["counts"]["evaluated"] == 3
    assert [row["symbol"] for row in lane["ranked_candidates"]] == ["SPY", "QQQ", "IWM"]
    assert "actionable_ranked_candidates" in lane
    assert all(row["ranking_lane"] == "benchmark" for row in lane["ranked_candidates"])
    assert lane["can_submit_orders"] is False
    # The context basket is intentionally optional: partial ETF coverage must
    # be explicit without turning the core discovery scanner into a false
    # failure or silently suppressing its candidates.
    context = report["coverage"]["market_context"]
    assert context["status"] == "partial"
    assert context["error_count"] == 0
    assert report["operational_health"] == "ok"
    assert any(warning.startswith("Market context incomplete:") for warning in report["warnings"])


def test_large_but_illiquid_move_is_not_precision_watch() -> None:
    row = evaluate_candidate(
        {"symbol": "PENNY", "sources": ["movers_gainers"], "source_ranks": {}},
        {"price": 1.25, "gap_return": 1.5, "spread_pct": 0.08, "snapshot_volume": 100_000},
        bar_features(_bars()),
        500_000,
        [],
        NOW_ET,
    )

    assert row["state"] == "filtered"
    assert "price_floor" in row["blockers"]
    assert "underlying_spread" in row["blockers"]
    assert "dollar_liquidity" in row["blockers"]
    assert row["can_submit_orders"] is False


def test_liquid_confirmed_move_has_levels_but_no_order_authority() -> None:
    row = evaluate_candidate(
        {"symbol": "NEWX", "sources": ["movers_gainers", "most_active_volume", "most_active_trades"], "source_ranks": {}},
        {"price": 11.0, "gap_return": 0.12, "spread_pct": 0.001, "snapshot_volume": 9_000_000},
        bar_features(_bars()),
        250_000_000,
        [{"headline": "Material company update"}],
        NOW_ET,
    )

    assert row["state"] == "precision_watch"
    assert row["price_action_confirmation"]["state"] == "bullish_confirmed"
    assert row["price_action_confirmation"]["pattern"] == "breakout_close"
    assert row["discovery_stage"] == "structure_observed"
    assert row["confirmation_stage"] == "completed_5m_confirmed"
    assert row["trade_levels"]["confirmation_trigger"] is not None
    assert row["trade_levels"]["invalidation"] is not None
    assert row["trade_levels"]["target_2r"] is not None
    assert row["execution_enabled"] is False
    assert "strategy_confirmation_and_revalidation_required" not in row["blockers"]
    assert row["entry"] == row["trade_levels"]["confirmation_trigger"]
    assert row["invalidation"] == row["trade_levels"]["invalidation"]


def test_unconfirmed_setup_still_flags_revalidation_blocker() -> None:
    unconfirmed_bars = bar_features(_bars())
    unconfirmed_bars["price_action_state"] = "waiting"
    row = evaluate_candidate(
        {"symbol": "WAIT", "sources": ["movers_gainers", "most_active_volume"], "source_ranks": {}},
        {"price": 11.0, "gap_return": 0.12, "spread_pct": 0.001, "snapshot_volume": 9_000_000},
        unconfirmed_bars,
        250_000_000,
        [{"headline": "Material company update"}],
        NOW_ET,
    )
    assert "strategy_confirmation_and_revalidation_required" in row["blockers"]


def test_intraday_radar_runner_updates_spy_level_monitor_before_alerting() -> None:
    root = Path(__file__).resolve().parents[2]
    runner = (root / "scripts" / "run_intraday_opportunity_radar.ps1").read_text(encoding="utf-8")

    assert "spy_level_reaction_shadow.py" in runner
    assert runner.index("spy_level_reaction_shadow.py") < runner.index("simple_price_action_alerts.py")


def test_already_extended_move_is_no_chase_and_cannot_enter_actionable_ranking() -> None:
    row = evaluate_candidate(
        {"symbol": "CHASE", "sources": ["movers_gainers", "most_active_volume"], "source_ranks": {}},
        {"price": 12.0, "gap_return": 0.20, "spread_pct": 0.001, "snapshot_volume": 9_000_000},
        bar_features(_bars()),
        250_000_000,
        [],
        NOW_ET,
    )

    assert row["remaining_opportunity"]["status"] == "late_no_chase"
    assert row["ranking_score"] < row["score"]
    assert row["actionable_for_ranking"] is False
    assert row["execution_enabled"] is False
    assert row["can_submit_orders"] is False


def test_unconfirmed_watch_cannot_enter_actionable_ranking() -> None:
    rows = _bars()
    rows[-1] = {**rows[-1], "h": 10.65, "l": 10.3, "o": 10.5, "c": 10.55}
    row = evaluate_candidate(
        {"symbol": "QQQ", "sources": ["known_liquid_leader", "most_active_volume"], "source_ranks": {}},
        {"price": 10.55, "gap_return": 0.01, "spread_pct": 0.001, "snapshot_volume": 9_000_000},
        bar_features(rows),
        500_000_000,
        [],
        NOW_ET,
    )

    assert row["confirmation_stage"] == "awaiting_completed_5m_confirmation"
    assert row["actionable_for_ranking"] is False


def test_inverted_directional_levels_are_suppressed() -> None:
    features = bar_features(_bars())
    features.update({
        "price_action_state": "bearish_confirmed",
        "opening_range_low": 10.0,
        "vwap_proxy": 9.8,
        "last_bar_high": 9.9,
    })

    row = evaluate_candidate(
        {"symbol": "BADGEO", "sources": ["movers_losers", "most_active_volume"], "source_ranks": {}},
        {"price": 9.7, "gap_return": -0.08, "spread_pct": 0.001, "snapshot_volume": 9_000_000},
        features,
        250_000_000,
        [],
        NOW_ET,
    )

    assert row["state"] == "filtered"
    assert row["trade_levels"]["invalidation"] is None
    assert row["trade_levels"]["target_2r"] is None
    assert "directional_level_geometry" in row["blockers"]


def test_cross_sectional_factor_consensus_rewards_breadth_and_spread_quality() -> None:
    rows = [
        {
            "symbol": "STRONG",
            "spread_pct": 0.08,
            "factor_scores": {"magnitude": 90, "volume_pace": 95, "liquidity": 92, "structure": 92, "discovery_breadth": 90, "catalyst": 88},
            "can_submit_orders": False,
        },
        {
            "symbol": "WEAK",
            "spread_pct": 1.2,
            "factor_scores": {"magnitude": 20, "volume_pace": 15, "liquidity": 25, "structure": 42, "discovery_breadth": 38, "catalyst": 45},
            "can_submit_orders": False,
        },
    ]

    ranked = apply_cross_sectional_factor_consensus(rows)

    assert ranked[0]["factor_consensus"]["score"] > ranked[1]["factor_consensus"]["score"]
    assert ranked[0]["factor_consensus"]["percentile_ranks"]["spread_quality"] == 100.0
    assert ranked[0]["factor_consensus"]["authority"] == "observe_only_no_gate_or_sizing_effect"
    assert ranked[0]["can_submit_orders"] is False


def test_cross_sectional_factor_consensus_reports_missing_data_without_imputation() -> None:
    ranked = apply_cross_sectional_factor_consensus([
        {"symbol": "PARTIAL", "spread_pct": None, "factor_scores": {"magnitude": 80}},
        {"symbol": "PEER", "spread_pct": 0.2, "factor_scores": {"magnitude": 30}},
    ])

    consensus = ranked[0]["factor_consensus"]
    assert consensus["status"] == "insufficient"
    assert consensus["data_completeness"] < 0.5
    assert "spread_quality" not in consensus["percentile_ranks"]


def test_cockpit_surfaces_intraday_coverage_and_candidate(tmp_path: Path) -> None:
    payload = {
        "generated_at": "2026-08-20T15:00:00Z",
        "operational_health": "ok",
        "session_status": "regular_session",
        "coverage": {"unique_symbols_discovered": 220, "symbols_evaluated": 50, "precision_watch_count": 2},
        "ranked_candidates": [{
            "symbol": "NEWX",
            "state": "precision_watch",
            "score": 88,
            "direction": "bullish",
            "setup": "opening_range_breakout",
            "change_pct": 12,
            "volume_pace_rvol_proxy": 3.2,
            "discovery_sources": ["movers_gainers", "most_active_volume"],
            "catalyst_available": True,
            "hard_gates": {"price_floor": True, "completed_5m_structure": True, "underlying_spread": True, "dollar_liquidity": True, "meaningful_move_or_activity": True},
            "blockers": ["strategy_confirmation_and_revalidation_required"],
            "factor_scores": {"magnitude": 90, "volume_pace": 90, "structure": 92, "liquidity": 88},
            "trade_levels": {"confirmation_trigger": 11.1, "invalidation": 10.7, "target_2r": 11.9},
        }],
    }
    (tmp_path / "intraday-opportunity-radar.json").write_text(json.dumps(payload), encoding="utf-8")

    cockpit = build_cockpit(report_dir=tmp_path, now=datetime.fromisoformat("2026-08-20T15:01:00+00:00"))
    candidate = next(row for row in cockpit["candidates"] if row["symbol"] == "NEWX")

    assert cockpit["discovery"]["coverage"]["unique_symbols_discovered"] == 220
    assert candidate["entry"] == 11.1
    assert candidate["paper_consumable"] is False
    assert candidate["setup_score"] >= 70


def test_move_review_distinguishes_early_late_and_not_evaluated() -> None:
    latest = {
        "date": "2026-08-20",
        "market_movers": [
            {"symbol": "EARLY", "percent_change": 20},
            {"symbol": "LATE", "percent_change": 20},
            {"symbol": "DEEP", "percent_change": 18},
        ],
    }
    history = [{
        "date": "2026-08-20",
        "as_of_et": "2026-08-20T10:00:00-04:00",
        "all_discovered_symbols": ["EARLY", "LATE", "DEEP"],
        "ranked_candidates": [
            {"symbol": "EARLY", "change_pct": 5, "grade": "B+", "state": "watch"},
            {"symbol": "LATE", "change_pct": 18, "grade": "A-", "state": "precision_watch"},
        ],
    }]

    review = build_review(latest, history)
    classified = {row["symbol"]: row["classification"] for row in review["moves"]}

    assert classified == {"EARLY": "detected_early", "LATE": "detected_late", "DEEP": "discovered_not_evaluated"}
    assert review["summary"]["actionable_early_count"] == 1
    rows = {row["symbol"]: row for row in review["moves"]}
    assert rows["EARLY"]["actionability"] == "actionable_early"
    assert rows["DEEP"]["filter_reasons"] == ["not_selected_for_intraday_bar_budget"]
