from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts.live_opportunity_engine import (
    SETUP_FAMILIES,
    LiveOpportunityEngine,
    _aggregate_rth_hourly,
    build_feed_provenance,
    _filter_completed_period_bars,
    _receive_control,
    project_radar_report,
)
from scripts.market_data_provider_registry import build_provider_registry


def _bars() -> list[dict[str, float | str]]:
    start = datetime(2026, 8, 21, 13, 30, tzinfo=timezone.utc)
    rows: list[dict[str, float | str]] = []
    price = 100.0
    for index in range(8):
        open_price = price
        close = price + (0.35 if index < 3 else 0.65)
        rows.append(
            {
                "t": (start + timedelta(minutes=5 * index)).isoformat().replace("+00:00", "Z"),
                "o": open_price,
                "h": close + 0.18,
                "l": open_price - 0.12,
                "c": close,
                "v": 500_000 + index * 80_000,
            }
        )
        price = close
    return rows


def test_feed_provenance_never_implies_unverified_sip() -> None:
    default = build_feed_provenance({})
    requested = build_feed_provenance({"VIBE_TRADING_STOCK_FEED": "sip"})

    assert default["feed"] == "iex"
    assert default["entitlement"] == "configured_not_verified"
    assert requested["feed"] == "sip"
    assert requested["entitlement"] == "configured_not_verified"
    assert default["execution_enabled"] is False
    assert requested["can_submit_orders"] is False


def test_hourly_context_is_anchored_to_rth_and_excludes_extended_hours() -> None:
    rows = [
        {"t": "2026-08-21T13:00:00Z", "o": 99.0, "h": 100.0, "l": 98.0, "c": 99.5, "v": 10},  # 08:00 ET
        {"t": "2026-08-21T14:30:00Z", "o": 100.0, "h": 101.0, "l": 99.5, "c": 100.5, "v": 20},
        {"t": "2026-08-21T15:00:00Z", "o": 100.5, "h": 102.0, "l": 100.0, "c": 101.5, "v": 30},
        {"t": "2026-08-21T15:30:00Z", "o": 101.5, "h": 103.0, "l": 101.0, "c": 102.5, "v": 40},
        {"t": "2026-08-21T21:00:00Z", "o": 102.5, "h": 104.0, "l": 102.0, "c": 103.5, "v": 50},  # 16:00 ET
    ]

    hourly = _aggregate_rth_hourly(rows)

    assert len(hourly) == 2
    assert hourly[0] == {"t": "2026-08-21T14:30:00Z", "o": 100.0, "h": 102.0, "l": 99.5, "c": 101.5, "v": 50.0}
    assert hourly[1] == {"t": "2026-08-21T15:30:00Z", "o": 101.5, "h": 103.0, "l": 101.0, "c": 102.5, "v": 40.0}


def test_daily_and_weekly_context_excludes_current_incomplete_periods() -> None:
    now = datetime(2026, 8, 21, 15, 0, tzinfo=timezone.utc)
    rows = [
        {"t": "2026-08-14T04:00:00Z", "o": 98.0, "h": 99.0, "l": 97.0, "c": 98.5, "v": 10},
        {"t": "2026-08-20T04:00:00Z", "o": 99.0, "h": 100.0, "l": 98.0, "c": 99.5, "v": 20},
        {"t": "2026-08-21T04:00:00Z", "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.5, "v": 30},
    ]

    daily = _filter_completed_period_bars(rows, timeframe="1Day", now=now)
    weekly = _filter_completed_period_bars(rows, timeframe="1Week", now=now)

    assert [row["t"] for row in daily] == ["2026-08-14T04:00:00Z", "2026-08-20T04:00:00Z"]
    assert [row["t"] for row in weekly] == ["2026-08-14T04:00:00Z"]


def test_live_engine_emits_ranked_read_only_setup_with_post_cost_geometry() -> None:
    engine = LiveOpportunityEngine(feed="iex")
    now = datetime(2026, 8, 21, 14, 10, tzinfo=timezone.utc)
    engine.seed_symbol(
        "NVDA",
        bars=_bars(),
        quote={"bid": 104.55, "ask": 104.57, "timestamp": now.isoformat()},
        average_dollar_volume=4_000_000_000,
        catalyst={"headline": "NVDA raises revenue outlook", "source": "sec", "freshness": "live"},
        benchmark_return=0.002,
        sector_return=0.004,
        previous_close=100.0,
    )

    report = engine.snapshot(now=now)

    assert report["mode"] == "read_only_streaming_research"
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["feed"]["feed"] == "iex"
    assert report["candidates"]
    top = report["candidates"][0]
    assert top["setup_family"] in SETUP_FAMILIES
    assert top["entry"] is not None
    assert top["invalidation"] is not None
    assert top["targets"]
    assert top["reward_risk_after_friction"] is not None
    assert top["source_labels"]
    assert top["freshness"] in {"live", "recent"}
    assert top["market_structure"]["decision"] in {"READY_TO_REVIEW", "WAIT", "REJECT", "STAND_ASIDE"}
    assert "best_setup" in top["market_structure"]
    assert "worst_setup" in top["market_structure"]
    assert top["market_structure"]["entry_plan"]
    assert top["market_structure"]["exit_plan"]
    assert top["market_structure"]["execution_enabled"] is False
    assert top["decision_score"] == top["market_structure"]["score"]
    assert top["grade"] == top["market_structure"]["grade"]
    assert top["market_structure"]["pattern_grade"]["can_submit_orders"] is False
    assert report["market_structure_patterns"]
    assert top["execution_enabled"] is False
    assert top["can_submit_orders"] is False


def test_live_engine_passes_completed_hourly_context_into_cisd_sequence() -> None:
    engine = LiveOpportunityEngine(feed="iex")
    now = datetime(2026, 8, 21, 14, 10, tzinfo=timezone.utc)
    rows = [
        {"t": f"2026-08-21T13:{20 + index * 5:02d}:00Z", "o": o, "h": h, "l": low, "c": close, "v": 200_000}
        for index, (o, h, low, close) in enumerate([
            (102.1, 102.25, 101.9, 102.05),
            (102.05, 102.2, 101.85, 102.0),
            (102.0, 102.2, 101.8, 102.0),
            (102.0, 102.1, 101.4, 101.5),
            (101.5, 101.6, 100.9, 101.0),
            (101.0, 101.25, 100.5, 101.1),
            (101.1, 101.95, 101.0, 101.9),
            (101.9, 102.3, 101.75, 102.2),
        ])
    ]
    hourly = [
        {"t": "2026-08-20T14:30:00Z", "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.5, "v": 1_000_000},
        {"t": "2026-08-20T15:30:00Z", "o": 100.5, "h": 102.0, "l": 100.0, "c": 101.5, "v": 1_000_000},
        {"t": "2026-08-21T13:30:00Z", "o": 103.0, "h": 104.0, "l": 102.5, "c": 103.5, "v": 1_000_000},
    ]
    engine.seed_symbol(
        "SPY",
        bars=rows,
        higher_timeframes={"60m": hourly},
        quote={"bid": 102.19, "ask": 102.21, "timestamp": now.isoformat()},
        average_dollar_volume=5_000_000_000,
    )

    report = engine.snapshot(now=now)

    setup = report["market_structure_watchlist"][0]["best_setup"]
    assert setup["pattern_id"] == "ict_cisd_universal_model"
    assert any(row["setup_family"] == "ict_cisd_universal_model" for row in report["candidates"])
    assert setup["model_sequence"]["mapped_execution_timeframe"] == "5m"
    watch = report["market_structure_watchlist"][0]
    assert "completed_60m_bars" in watch["source_labels"]
    assert {row["id"] for row in watch["liquidity_level_context"]["levels"]} >= {"pdh", "pdl"}
    assert watch["participation_context"]["true_order_flow"] is False
    assert watch["macro_context"]["score_effect"] == "none_until_validated"
    assert setup["execution_enabled"] is False
    assert setup["can_submit_orders"] is False


def test_stale_quote_forces_stand_aside_even_when_structure_is_strong() -> None:
    engine = LiveOpportunityEngine(feed="iex")
    now = datetime(2026, 8, 21, 14, 10, tzinfo=timezone.utc)
    engine.seed_symbol(
        "AMD",
        bars=_bars(),
        quote={"bid": 104.55, "ask": 104.57, "timestamp": (now - timedelta(minutes=3)).isoformat()},
        average_dollar_volume=1_000_000_000,
        catalyst={"headline": "Fresh event", "source": "sec", "freshness": "live"},
        benchmark_return=0.001,
        sector_return=0.002,
        previous_close=100.0,
    )

    report = engine.snapshot(now=now)

    assert report["decision_state"] == "STAND_ASIDE"
    assert report["ready_count"] == 0
    assert any("stale_quote" in row["blockers"] for row in report["candidates"])


def test_all_preregistered_setup_families_are_declared_and_frozen() -> None:
    assert SETUP_FAMILIES == (
        "catalyst_continuation",
        "opening_range_break_retest",
        "vwap_reclaim_pullback",
        "liquidity_sweep_mss_retest",
        "cbc_strong_flip",
        "session_liquidity_sweep_reclaim",
        "ict_cisd_universal_model",
        "relative_weakness_breakdown",
        "failed_breakout_reversal",
    )


def test_provider_registry_reports_presence_without_serializing_secrets() -> None:
    report = build_provider_registry({
        "ALPACA_API_KEY": "sensitive-key",
        "ALPACA_SECRET_KEY": "sensitive-secret",
        "SEC_USER_AGENT": "Vibe research@example.com",
    })

    serialized = str(report)
    statuses = {row["name"]: row["status"] for row in report["providers"]}
    assert statuses["alpaca"] == "configured"
    assert statuses["sec_edgar"] == "configured"
    assert "sensitive-key" not in serialized
    assert "sensitive-secret" not in serialized
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False


def test_stream_handshake_rejects_error_control_frames() -> None:
    class Socket:
        def recv(self) -> str:
            return '[{"T":"error","code":401,"msg":"not authenticated"}]'

    try:
        _receive_control(Socket(), expected_type="success", expected_message="authenticated")
    except RuntimeError as exc:
        assert str(exc) == "alpaca_stream_error_401"
    else:
        raise AssertionError("control-frame error was not rejected")


def test_rest_fallback_is_explicit_in_mode_and_provenance() -> None:
    engine = LiveOpportunityEngine(feed="iex")
    engine.transport = "rest_polling"

    report = engine.snapshot(now=datetime(2026, 8, 21, 14, 10, tzinfo=timezone.utc))

    assert report["mode"] == "read_only_rest_polling_research"
    assert report["feed"]["transport"] == "rest_polling"
    assert report["feed"]["label"] == "alpaca_iex_rest_polling"
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False


def test_scheduled_fallback_never_reuses_plus_minus_grades_as_canonical() -> None:
    report = project_radar_report({
        "date": "2026-08-21",
        "generated_at": "2026-08-21T20:00:00Z",
        "ranked_candidates": [{
            "symbol": "SPY",
            "score": 82.0,
            "grade": "A-",
            "direction": "bullish",
            "setup": "opening_range",
            "blockers": [],
            "trade_levels": {"confirmation_trigger": 650.0, "invalidation": 648.0, "target_2r": 654.0},
        }],
    })

    row = report["candidates"][0]
    assert row["grade"] == "B"
    assert row["score_basis"] == "scheduled_radar_legacy_not_pattern_grade_v1"
    assert "pattern_grade_v1_unavailable_in_fallback" in row["source_labels"]
    assert row["state"] == "WATCH"
