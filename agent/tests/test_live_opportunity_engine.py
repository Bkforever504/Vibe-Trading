from __future__ import annotations

import json
import sys
import threading
import types
from datetime import datetime, timedelta, timezone

from scripts.live_opportunity_engine import (
    SETUP_FAMILIES,
    LiveOpportunityEngine,
    _alpaca_market_event,
    _aggregate_rth_hourly,
    _aggregate_rth_four_hour,
    _with_core_context_symbols,
    build_feed_provenance,
    _filter_completed_period_bars,
    _data_quality_context,
    _market_risk_context,
    _quote_context,
    _receive_control,
    _session_risk_context,
    project_radar_report,
    run_stream,
)
from scripts.intraday_opportunity_radar import CORE_LIQUID_SYMBOLS
from scripts.market_data_provider_registry import build_provider_registry
from scripts.priority_focus_universe import PRIORITY_FOCUS_UNIVERSE
from agent.src.market_data.event_eyes import EventKind, MarketEvent


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


def test_all_core_liquid_symbols_are_reserved_inside_broker_limit() -> None:
    discovered = [f"S{index:03d}" for index in range(110)]

    symbols = _with_core_context_symbols(discovered)

    assert symbols[: len(CORE_LIQUID_SYMBOLS)] == list(CORE_LIQUID_SYMBOLS)
    assert "TSLA" in symbols
    assert len(symbols) == 100
    assert len(set(symbols)) == 100


def test_core_liquid_symbols_are_deduplicated_before_dynamic_capacity_is_filled() -> None:
    discovered = ["tsla", "SPY", "NVDA", *[f"D{index:03d}" for index in range(100)]]

    symbols = _with_core_context_symbols(discovered)

    assert symbols[: len(CORE_LIQUID_SYMBOLS)] == list(CORE_LIQUID_SYMBOLS)
    assert symbols.count("TSLA") == 1
    assert symbols.count("SPY") == 1
    assert len(symbols) == 100


def test_websocket_subscription_is_capped_at_basic_plan_limit_and_keeps_core(
    monkeypatch, tmp_path,
) -> None:
    stop = threading.Event()
    sent: list[dict[str, object]] = []

    class FakeWebSocket:
        def __init__(self) -> None:
            self.responses = [
                '[{"T":"success","msg":"connected"}]',
                '[{"T":"success","msg":"authenticated"}]',
                '[{"T":"subscription","quotes":[],"bars":[]}]',
            ]

        def recv(self) -> str:
            response = self.responses.pop(0)
            if not self.responses:
                stop.set()
            return response

        def send(self, payload: str) -> None:
            sent.append(json.loads(payload))

        def close(self) -> None:
            return None

    socket = FakeWebSocket()
    monkeypatch.setitem(sys.modules, "websocket", types.SimpleNamespace(create_connection=lambda *_args, **_kwargs: socket))
    monkeypatch.setattr("scripts.live_opportunity_engine._load_alpaca_credentials", lambda: ("key", "secret"))
    symbols = _with_core_context_symbols([f"S{index:03d}" for index in range(110)])

    result = run_stream(
        LiveOpportunityEngine(feed="iex"),
        symbols,
        report_path=tmp_path / "live.json",
        stop_event=stop,
    )

    subscription = next(row for row in sent if row.get("action") == "subscribe")
    assert result == 0
    subscribed = subscription["quotes"]
    assert subscribed[:len(PRIORITY_FOCUS_UNIVERSE)] == list(PRIORITY_FOCUS_UNIVERSE)
    assert len(subscribed) == 30
    assert subscription["bars"] == subscribed
    assert subscription["trades"] == subscribed
    assert subscription["updatedBars"] == subscribed
    assert subscription["statuses"] == subscribed
    assert subscription["lulds"] == subscribed
    assert "corrections" not in subscription
    assert "cancelErrors" not in subscription
    assert list(CORE_LIQUID_SYMBOLS) == symbols[: len(CORE_LIQUID_SYMBOLS)]
    assert "DELL" in symbols[:30]


def test_alpaca_event_normalization_and_engine_shadow_tape_state() -> None:
    received = datetime(2026, 9, 4, 14, 30, 1, tzinfo=timezone.utc)
    event = _alpaca_market_event({
        "T": "q", "S": "QQQ", "bp": 100.0, "ap": 100.02,
        "bs": 10, "as": 12, "t": "2026-09-04T14:30:00Z",
    }, received_at=received)
    assert event is not None and event.kind == EventKind.QUOTE
    engine = LiveOpportunityEngine(feed="sip")
    card = engine.update_market_event(event, now=received)
    assert card["last_integrity"]["accepted"] is True
    assert card["quote_persistence"]["state"] == "OBSERVING"
    assert "luld_unavailable" in card["shadow_vetoes"]
    assert card["execution_enabled"] is False


def test_alpaca_cancel_error_uses_trade_id_and_status_codes_are_centralized() -> None:
    received = datetime(2026, 9, 4, 14, 30, 1, tzinfo=timezone.utc)
    cancelled = _alpaca_market_event({
        "T": "x", "S": "QQQ", "i": 712, "p": 100.0, "s": 5,
        "t": "2026-09-04T14:30:00Z",
    }, received_at=received)
    assert cancelled is not None and cancelled.original_sequence == 712
    engine = LiveOpportunityEngine(feed="sip")
    card = engine.update_market_event(cancelled, now=received)
    assert card["last_integrity"]["accepted"] is True
    halted = _alpaca_market_event({
        "T": "s", "S": "QQQ", "sc": "P", "rc": "LUDP",
        "t": "2026-09-04T14:30:01Z",
    }, received_at=received + timedelta(seconds=1))
    assert halted is not None
    status = engine.update_market_event(halted, now=received + timedelta(seconds=1))
    assert "halt_or_pause" in status["shadow_vetoes"]
    assert halted.reason_code == "LUDP"


def test_alpaca_resume_reason_clears_halt_without_guessing_unknown_status() -> None:
    now = datetime(2026, 9, 4, 14, 30, tzinfo=timezone.utc)
    engine = LiveOpportunityEngine(feed="sip")
    for code, reason, offset in (("H", "T1", 0), ("F", "R4", 1)):
        event = _alpaca_market_event({
            "T": "s", "S": "QQQ", "sc": code, "rc": reason,
            "t": (now + timedelta(seconds=offset)).isoformat(),
        }, received_at=now + timedelta(seconds=offset))
        assert event is not None
        card = engine.update_market_event(event, now=now + timedelta(seconds=offset))
    assert card["tape_truth"]["halted"] is False
    assert card["tape_truth"]["reason"] == "trading_resumed"


def test_event_lane_emits_paired_shadow_heads_up_after_level_and_quote_hold() -> None:
    now = datetime(2026, 8, 21, 14, 10, tzinfo=timezone.utc)
    engine = LiveOpportunityEngine(feed="sip")
    engine.seed_symbol(
        "QQQ", bars=_bars(),
        quote={"bid": 104.55, "ask": 104.57, "timestamp": now.isoformat()},
        average_dollar_volume=4_000_000_000,
        catalyst={"headline": "fresh", "source": "sec"},
        previous_close=100.0,
    )
    initial = engine.snapshot(now=now)
    candidate = initial["candidates"][0]
    level = float(candidate["entry"])
    engine.update_market_event(MarketEvent(
        symbol="QQQ", kind=EventKind.LULD, event_ts=now, received_ts=now,
        source="alpaca_sip", lower_band=level * 0.9, upper_band=level * 1.1,
    ), now=now)
    for seconds in (0.1, 2.6, 5.2):
        stamp = now + timedelta(seconds=seconds)
        engine.update_market_event(MarketEvent(
            symbol="QQQ", kind=EventKind.QUOTE, event_ts=stamp, received_ts=stamp,
            source="alpaca_sip", bid=level - 0.01, ask=level + 0.01,
            bid_size=20, ask_size=20,
        ), now=stamp)
    report = engine.snapshot(now=now + timedelta(seconds=5.2))
    heads_up = [row for row in report["event_time_intelligence"]["lifecycle"] if row["state"] == "SHADOW_HEADS_UP"]
    assert heads_up
    assert heads_up[0]["pair_id"] == candidate["event_pair_id"]
    assert heads_up[0]["notification_authority"] == "dashboard_shadow_only"


def test_mapped_level_can_emit_before_completed_bar_candidate_then_pair() -> None:
    now = datetime(2026, 8, 21, 14, 10, tzinfo=timezone.utc)
    probe = LiveOpportunityEngine(feed="sip")
    probe.seed_symbol(
        "QQQ", bars=_bars(),
        quote={"bid": 104.55, "ask": 104.57, "timestamp": now.isoformat()},
        average_dollar_volume=4_000_000_000,
        catalyst={"headline": "fresh", "source": "sec"}, previous_close=100.0,
    )
    mapped_candidate = probe.snapshot(now=now)["candidates"][0]
    family = mapped_candidate["setup_family"]
    level = mapped_candidate["entry"]
    engine = LiveOpportunityEngine(feed="sip")
    engine.seed_symbol(
        "QQQ", bars=_bars(), quote={}, average_dollar_volume=4_000_000_000,
        catalyst={"headline": "fresh", "source": "sec"}, previous_close=100.0,
        mapped_levels={"confirmation_trigger": level},
        mapped_setup_family=family, mapped_direction=mapped_candidate["direction"],
    )
    engine.update_market_event(MarketEvent(
        symbol="QQQ", kind=EventKind.LULD, event_ts=now, received_ts=now,
        source="alpaca_sip", lower_band=90, upper_band=110,
    ), now=now)
    for seconds in (0.1, 2.6, 5.2, 7.8):
        stamp = now + timedelta(seconds=seconds)
        engine.update_market_event(MarketEvent(
            symbol="QQQ", kind=EventKind.QUOTE, event_ts=stamp, received_ts=stamp,
            source="alpaca_sip", bid=level - 0.01, ask=level + 0.01, bid_size=20, ask_size=20,
        ), now=stamp)
    before = list(engine._event_lifecycle)
    assert any(row["state"] == "SHADOW_HEADS_UP" for row in before)
    assert all(row["paired_bar_lane"] == "awaiting_completed_5m_candidate" for row in before)
    report = engine.snapshot(now=now + timedelta(seconds=8))
    matching = [
        row for row in report["event_time_intelligence"]["lifecycle"]
        if row["pair_id"].endswith(f":{family}")
    ]
    assert any(row["paired_bar_lane"] == "completed_5m_candidate_observed" for row in matching)
    assert all(row.get("event_to_bar_seconds", -1) >= 0 for row in matching)
    frozen = [(row.get("bar_signal_available_at"), row.get("event_to_bar_seconds")) for row in matching]
    later = engine.snapshot(now=now + timedelta(minutes=2))
    later_matching = [
        row for row in later["event_time_intelligence"]["lifecycle"]
        if row["pair_id"].endswith(f":{family}")
    ]
    assert [(row.get("bar_signal_available_at"), row.get("event_to_bar_seconds")) for row in later_matching] == frozen


def test_event_intensity_uses_prior_completed_windows_and_persistence() -> None:
    start = datetime(2026, 8, 21, 14, 10, tzinfo=timezone.utc)
    engine = LiveOpportunityEngine(feed="sip")
    engine.seed_symbol("QQQ", bars=[], quote={})
    for bucket, count in ((0, 1), (10, 1), (20, 4), (30, 4)):
        for index in range(count):
            stamp = start + timedelta(seconds=bucket, milliseconds=index * 10)
            engine.update_market_event(MarketEvent(
                symbol="QQQ", kind=EventKind.QUOTE, event_ts=stamp, received_ts=stamp,
                source="alpaca_sip", bid=100, ask=100.02, bid_size=10, ask_size=10,
            ), now=stamp)
            engine.update_market_event(MarketEvent(
                symbol="QQQ", kind=EventKind.TRADE, event_ts=stamp, received_ts=stamp,
                source="alpaca_sip", price=100.01, size=10, conditions=("@",),
            ), now=stamp)
    card = engine.snapshot(now=start + timedelta(seconds=40))["event_time_intelligence"]["event_intensity"]["QQQ"]
    assert card["status"] == "observed"
    assert card["state"] == "ACCELERATING"
    assert card["persistence_windows"] == 2


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


def test_four_hour_context_uses_only_eight_completed_rth_thirty_minute_bars() -> None:
    start = datetime(2026, 8, 21, 13, 30, tzinfo=timezone.utc)
    rows = [
        {
            "t": (start + timedelta(minutes=30 * index)).isoformat().replace("+00:00", "Z"),
            "o": 100.0 + index,
            "h": 101.0 + index,
            "l": 99.0 + index,
            "c": 100.5 + index,
            "v": 10,
        }
        for index in range(10)
    ]

    four_hour = _aggregate_rth_four_hour(rows)

    assert len(four_hour) == 1
    assert four_hour[0]["t"] == "2026-08-21T13:30:00Z"
    assert four_hour[0]["h"] == 108.0
    assert four_hour[0]["l"] == 99.0
    assert four_hour[0]["v"] == 80.0


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


def test_fresh_market_risk_stand_aside_is_a_hard_veto_with_provenance() -> None:
    now = datetime(2026, 8, 24, 19, 55, tzinfo=timezone.utc)
    report = {
        "generated_at": "2026-08-24T19:54:04Z",
        "provider": "market_catalyst_calendar",
        "today": {
            "date": "2026-08-24",
            "max_impact": "high",
            "allowed_playbooks": ["stand_aside"],
            "vetoes": ["dynamic_geopolitical_risk"],
            "dynamic_risk": {"risk_level": "high", "recommended_posture": "stand_aside"},
        },
    }

    context = _market_risk_context(report, now=now, required=True)

    assert context["status"] == "stand_aside"
    assert context["hard_veto"] is True
    assert context["macro_event_window"] is True
    assert context["source_label"] == "market_catalyst_calendar"
    assert context["execution_enabled"] is False
    assert context["can_submit_orders"] is False


def test_stale_required_market_risk_context_fails_closed() -> None:
    now = datetime(2026, 8, 24, 19, 55, tzinfo=timezone.utc)
    report = {"generated_at": "2026-08-24T16:00:00Z", "today": {"date": "2026-08-24"}}

    context = _market_risk_context(report, now=now, required=True)

    assert context["status"] == "stale"
    assert context["hard_veto"] is True
    assert "market_risk_context_stale" in context["blockers"]


def test_quote_and_completed_bar_integrity_fail_closed() -> None:
    now = datetime(2026, 8, 21, 14, 10, tzinfo=timezone.utc)
    crossed = _quote_context({"bid": 101.0, "ask": 100.0, "bid_size": 8, "ask_size": 2, "timestamp": now.isoformat()}, now)
    rows = _bars()
    rows[-1] = {**rows[-1], "h": 90.0}

    quality = _data_quality_context(rows, crossed, now=now)

    assert crossed["market_state"] == "crossed"
    assert crossed["bid_size"] == 8
    assert quality["status"] == "blocked"
    assert "crossed_quote" in quality["blockers"]
    assert "malformed_ohlc" in quality["blockers"]
    assert quality["execution_enabled"] is False


def test_iex_quote_scope_is_explicitly_degraded_not_mislabeled_nbbo() -> None:
    now = datetime(2026, 8, 21, 14, 10, tzinfo=timezone.utc)
    quote = _quote_context({"bid": 104.0, "ask": 104.02, "timestamp": now.isoformat()}, now)

    quality = _data_quality_context(_bars(), quote, now=now, consolidated_quote=False)

    assert quality["status"] == "degraded"
    assert "consolidated_nbbo_unavailable" in quality["warnings"]
    assert quality["quote_scope"] == "single_venue_iex_not_nbbo"


def test_stale_completed_bars_block_during_regular_session() -> None:
    now = datetime(2026, 8, 21, 15, 0, tzinfo=timezone.utc)
    quote = _quote_context({"bid": 104.0, "ask": 104.02, "timestamp": now.isoformat()}, now)

    quality = _data_quality_context(_bars(), quote, now=now)

    assert quality["status"] == "blocked"
    assert "stale_primary_bars" in quality["blockers"]


def test_session_risk_marks_open_and_close_buffers_as_stand_aside() -> None:
    opening = _session_risk_context(datetime(2026, 8, 24, 13, 32, tzinfo=timezone.utc))
    normal = _session_risk_context(datetime(2026, 8, 24, 14, 30, tzinfo=timezone.utc))
    closing = _session_risk_context(datetime(2026, 8, 24, 19, 55, tzinfo=timezone.utc))

    assert opening["hard_veto"] is True
    assert opening["phase"] == "opening_auction_buffer"
    assert normal["hard_veto"] is False
    assert normal["phase"] == "morning_session"
    assert closing["hard_veto"] is True
    assert closing["phase"] == "closing_auction_buffer"


def test_session_risk_honors_official_2026_nyse_holiday_and_early_close() -> None:
    holiday = _session_risk_context(datetime(2026, 11, 26, 16, 0, tzinfo=timezone.utc))
    early_close_buffer = _session_risk_context(datetime(2026, 11, 27, 17, 55, tzinfo=timezone.utc))

    assert holiday["phase"] == "exchange_holiday"
    assert holiday["hard_veto"] is True
    assert early_close_buffer["phase"] == "closing_auction_buffer"
    assert early_close_buffer["scheduled_close_et"] == "13:00"


def test_engine_applies_required_market_risk_veto_to_every_candidate(tmp_path) -> None:
    now = datetime(2026, 8, 21, 14, 10, tzinfo=timezone.utc)
    path = tmp_path / "market-risk.json"
    path.write_text(json.dumps({
        "generated_at": now.isoformat(),
        "provider": "market_catalyst_calendar",
        "today": {
            "date": "2026-08-21",
            "allowed_playbooks": ["stand_aside"],
            "max_impact": "high",
            "dynamic_risk": {"risk_level": "high", "recommended_posture": "stand_aside"},
        },
    }), encoding="utf-8")
    engine = LiveOpportunityEngine(feed="iex", risk_report_path=path)
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

    assert report["market_risk_context"]["hard_veto"] is True
    assert report["ready_count"] == 0
    assert all("market_risk_stand_aside" in row["blockers"] for row in report["candidates"])


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


def test_live_engine_can_refresh_higher_timeframe_context_without_reseeding_symbol() -> None:
    engine = LiveOpportunityEngine(feed="iex")
    engine.seed_symbol("SPY", bars=_bars(), quote={}, higher_timeframes={"1d": _bars()})
    refreshed = _bars()
    refreshed[-1]["c"] = 111.0

    engine.update_higher_timeframes("SPY", {"1d": refreshed}, refreshed_at="2026-08-21T15:00:00Z")

    state = engine._symbols["SPY"]  # white-box assertion for the refresh contract
    assert state["higher_timeframes"]["1d"][-1]["c"] == 111.0
    assert state["higher_timeframes_refreshed_at"] == "2026-08-21T15:00:00Z"


def test_live_engine_supplies_spy_qqq_smt_proxy_to_watchlist() -> None:
    engine = LiveOpportunityEngine(feed="iex")
    now = datetime(2026, 8, 21, 14, 10, tzinfo=timezone.utc)
    qqq = _bars()
    spy = _bars()
    qqq[-1]["h"] = max(float(row["h"]) for row in qqq[:-1]) + 1.0
    spy[-1]["h"] = max(float(row["h"]) for row in spy[:-1]) - 0.05
    engine.seed_symbol("QQQ", bars=qqq, quote={"bid": 104.5, "ask": 104.52, "timestamp": now.isoformat()})
    engine.seed_symbol("SPY", bars=spy, quote={"bid": 104.4, "ask": 104.42, "timestamp": now.isoformat()})

    report = engine.snapshot(now=now)

    qqq_watch = next(row for row in report["market_structure_watchlist"] if row["symbol"] == "QQQ")
    assert qqq_watch["smt_divergence_context"]["peer_symbol"] == "SPY"
    assert qqq_watch["smt_divergence_context"]["status"] == "divergence_observed"
    assert qqq_watch["smt_divergence_context"]["score_effect"] == "none_until_local_validation"
    assert qqq_watch["clc_entry_context"]["can_submit_orders"] is False


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
