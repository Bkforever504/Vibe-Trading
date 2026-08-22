from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.daily_move_coverage_review import build_review
from scripts.intraday_opportunity_radar import (
    apply_cross_sectional_factor_consensus,
    bar_features,
    coverage_trace,
    discovery_map,
    evaluate_candidate,
    nominate_symbols,
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
    assert row["trade_levels"]["confirmation_trigger"] is not None
    assert row["trade_levels"]["invalidation"] is not None
    assert row["trade_levels"]["target_2r"] is not None
    assert row["execution_enabled"] is False
    assert "strategy_confirmation_and_revalidation_required" in row["blockers"]


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
