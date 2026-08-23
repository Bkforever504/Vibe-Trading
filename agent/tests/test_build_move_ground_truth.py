from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from scripts.build_move_ground_truth import (
    build_ground_truth_report,
    build_labels,
    compute_prior_atr14,
    fetch_alpaca_bars,
    fetch_databento_timeframes,
    frozen_macro_windows,
    label_trigger,
)


def _bar(stamp: datetime, *, close: float = 100.0, high: float | None = None, low: float | None = None) -> dict:
    return {
        "t": stamp.isoformat().replace("+00:00", "Z"),
        "o": close,
        "h": close + 0.2 if high is None else high,
        "l": close - 0.2 if low is None else low,
        "c": close,
        "v": 1_000,
    }


def _five_minute_bars(*, trigger: datetime, future_closes: list[float]) -> tuple[list[dict], int]:
    # Fifteen completed bars are supplied so all fourteen prior true ranges can
    # use an earlier close without borrowing from the trigger or future.
    bars = [_bar(trigger - timedelta(minutes=5 * offset)) for offset in range(15, 0, -1)]
    trigger_index = len(bars)
    bars.append(_bar(trigger))
    bars.extend(_bar(trigger + timedelta(minutes=5 * offset), close=value) for offset, value in enumerate(future_closes, 1))
    return bars, trigger_index


def _timeframe_bars(*, trigger: datetime, interval: timedelta, future_closes: list[float]) -> tuple[list[dict], int]:
    bars = [_bar(trigger - interval * offset) for offset in range(15, 0, -1)]
    trigger_index = len(bars)
    bars.append(_bar(trigger))
    bars.extend(_bar(trigger + interval * offset, close=value) for offset, value in enumerate(future_closes, 1))
    return bars, trigger_index


def test_atr14_uses_only_fourteen_bars_completed_before_trigger() -> None:
    trigger = datetime(2026, 8, 24, 14, 30, tzinfo=timezone.utc)
    bars, trigger_index = _five_minute_bars(trigger=trigger, future_closes=[110.0] * 12)

    before = compute_prior_atr14(bars, trigger_index)
    bars[trigger_index]["h"] = 1_000.0
    bars[trigger_index + 1]["l"] = 0.0
    after = compute_prior_atr14(bars, trigger_index)

    assert before == pytest.approx(0.4)
    assert after == pytest.approx(before)


def test_long_move_requires_magnitude_r_and_sixty_percent_retention() -> None:
    trigger = datetime(2026, 8, 24, 14, 30, tzinfo=timezone.utc)
    bars, index = _five_minute_bars(
        trigger=trigger,
        future_closes=[100.1, 100.2, 100.36, 100.38, 100.4, 100.4, 100.39, 100.4, 100.38, 100.4, 100.39, 100.4],
    )

    row = label_trigger(bars, index, symbol="SPY", timeframe="5m", data_source="injected_test")

    assert row["label"] == 1
    assert row["direction"] == "bullish"
    assert row["atr14"] == pytest.approx(0.4)
    assert row["achievable_r_long"] >= 1.5
    assert row["retention_long"] >= 0.6
    assert row["excluded"] is False
    assert row["execution_enabled"] is False
    assert row["can_submit_orders"] is False


def test_short_move_is_labeled_independently() -> None:
    trigger = datetime(2026, 8, 24, 14, 30, tzinfo=timezone.utc)
    bars, index = _five_minute_bars(
        trigger=trigger,
        future_closes=[99.9, 99.8, 99.62, 99.6, 99.6, 99.61, 99.6, 99.62, 99.6, 99.61, 99.6, 99.6],
    )

    row = label_trigger(bars, index, symbol="QQQ", timeframe="5m", data_source="injected_test")

    assert row["label"] == -1
    assert row["direction"] == "bearish"
    assert row["achievable_r_short"] >= 1.5
    assert row["retention_short"] >= 0.6


@pytest.mark.parametrize(
    ("timeframe", "interval", "horizon", "favorable_close", "threshold"),
    [
        ("5m", timedelta(minutes=5), 12, 100.31, 0.30),
        ("15m", timedelta(minutes=15), 8, 100.51, 0.50),
        ("1h", timedelta(hours=1), 6, 100.76, 0.75),
        ("D", timedelta(days=1), 3, 101.26, 1.25),
    ],
)
def test_each_frozen_equity_timeframe_uses_its_own_horizon_and_threshold(
    timeframe: str,
    interval: timedelta,
    horizon: int,
    favorable_close: float,
    threshold: float,
) -> None:
    trigger = datetime(2026, 8, 24, 14, 0, tzinfo=timezone.utc) if timeframe != "D" else datetime(2026, 8, 24, tzinfo=timezone.utc)
    bars, index = _timeframe_bars(trigger=trigger, interval=interval, future_closes=[favorable_close] * horizon)

    row = label_trigger(bars, index, symbol="SPY", timeframe=timeframe, data_source="injected_test")

    assert row["label"] == 1
    assert row["horizon_bars"] == horizon
    assert row["magnitude_threshold"] == threshold


def test_late_wick_fails_retention_and_is_no_move() -> None:
    trigger = datetime(2026, 8, 24, 14, 30, tzinfo=timezone.utc)
    bars, index = _five_minute_bars(trigger=trigger, future_closes=[100.0] * 11 + [100.5])
    bars[-1]["h"] = 100.8

    row = label_trigger(bars, index, symbol="IWM", timeframe="5m", data_source="injected_test")

    assert row["label"] == 0
    assert row["retention_long"] < 0.6
    assert "retention_below_60pct" in row["label_reason"]


def test_stop_before_later_target_cannot_be_called_achievable_r() -> None:
    trigger = datetime(2026, 8, 24, 14, 30, tzinfo=timezone.utc)
    bars, index = _five_minute_bars(trigger=trigger, future_closes=[99.7] + [100.5] * 11)

    row = label_trigger(bars, index, symbol="SPY", timeframe="5m", data_source="injected_test")

    assert row["achievable_r_long"] >= 1.5
    assert row["target_before_stop_long"] is False
    assert row["long_checks"]["r_multiple"] is False
    assert row["label"] == 0


def test_macro_trigger_is_excluded_not_a_true_negative() -> None:
    trigger = datetime(2026, 8, 24, 14, 30, tzinfo=timezone.utc)
    bars, index = _five_minute_bars(trigger=trigger, future_closes=[100.5] * 12)

    row = label_trigger(
        bars,
        index,
        symbol="SPY",
        timeframe="5m",
        data_source="injected_test",
        macro_windows=[(trigger - timedelta(minutes=15), trigger + timedelta(minutes=15), "CPI")],
    )

    assert row["label"] is None
    assert row["excluded"] is True
    assert row["excluded_reason"] == "macro_event_window:CPI"


def test_equity_opening_trigger_measurement_begins_at_1000_et() -> None:
    trigger = datetime(2026, 8, 24, 13, 35, tzinfo=timezone.utc)  # 09:35 ET
    # The first four bars (09:40-09:55) are deliberately extreme and must be
    # ignored.  The twelve-bar measurement begins with the 10:00 close.
    bars, index = _five_minute_bars(trigger=trigger, future_closes=[100.7] * 4 + [100.4] * 12)

    row = label_trigger(bars, index, symbol="SPY", timeframe="5m", data_source="injected_test")

    assert row["measurement_start_ts"] == "2026-08-24T14:00:00Z"
    assert row["horizon_bars_observed"] == 12
    assert row["label"] == 1


def test_build_labels_marks_unmatured_horizons_excluded() -> None:
    trigger = datetime(2026, 8, 24, 14, 30, tzinfo=timezone.utc)
    bars, _ = _five_minute_bars(trigger=trigger, future_closes=[100.4] * 5)

    rows = build_labels(
        symbol="SPY",
        timeframe="5m",
        bars=bars,
        target_date=date(2026, 8, 24),
        data_source="injected_test",
    )

    assert rows
    assert any(row["excluded_reason"] == "insufficient_completed_horizon" for row in rows)
    assert all(row["execution_enabled"] is False and row["can_submit_orders"] is False for row in rows)


def test_full_universe_report_fails_closed_without_futures_entitlement() -> None:
    trigger = datetime(2026, 8, 24, 14, 30, tzinfo=timezone.utc)
    spy_bars, _ = _five_minute_bars(trigger=trigger, future_closes=[100.4] * 12)

    report = build_ground_truth_report(
        bars_by_pair={("SPY", "5m"): spy_bars},
        requested_pairs=[("SPY", "5m"), ("MES", "5m")],
        target_date=date(2026, 8, 24),
        data_sources={("SPY", "5m"): "alpaca_iex"},
    )

    assert report["metrics_qualified"] is False
    assert report["ground_truth_status"] == "partial_fail_closed"
    assert report["source_failures"] == [
        {
            "instrument": "MES",
            "timeframe": "5m",
            "reason": "bars_unavailable_or_not_entitled",
            "execution_enabled": False,
            "can_submit_orders": False,
        }
    ]
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["pattern_annotation_qualified"] is False
    assert len(report["rule_hash"]) == 64
    assert all(row["rule_hash"] == report["rule_hash"] for row in report["rows"])


def test_missing_macro_calendar_quarantines_rows_instead_of_leaking_partial_truth() -> None:
    trigger = datetime(2026, 8, 24, 14, 30, tzinfo=timezone.utc)
    bars, _ = _five_minute_bars(trigger=trigger, future_closes=[100.4] * 12)

    report = build_ground_truth_report(
        bars_by_pair={("SPY", "5m"): bars},
        requested_pairs=[("SPY", "5m")],
        target_date=date(2026, 8, 24),
        data_sources={("SPY", "5m"): "injected_test"},
        macro_context_qualified=False,
    )

    assert report["metrics_qualified"] is False
    assert all(row["excluded"] for row in report["rows"])
    assert {row["excluded_reason"] for row in report["rows"]} <= {
        "trigger_outside_eligible_session",
        "macro_calendar_coverage_unavailable",
    }
    assert any(failure["reason"] == "macro_calendar_coverage_unavailable" for failure in report["source_failures"])


def test_futures_require_explicit_rth_or_eth_provenance() -> None:
    trigger = datetime(2026, 8, 24, 15, 0, tzinfo=timezone.utc)
    bars, index = _five_minute_bars(trigger=trigger, future_closes=[106.0] * 12)

    missing = label_trigger(bars, index, symbol="MES", timeframe="5m", data_source="injected_test")
    for bar in bars:
        bar["session"] = "RTH"
        bar["session_date"] = "2026-08-24"
    explicit = label_trigger(bars, index, symbol="MES", timeframe="5m", data_source="injected_test")

    assert missing["excluded_reason"] == "trigger_outside_eligible_session"
    assert explicit["label"] == 1
    assert explicit["magnitude_threshold"] == 5.0
    assert explicit["magnitude_threshold_unit"] == "points"


def test_frozen_macro_calendar_expands_release_by_fifteen_minutes_and_expires_closed() -> None:
    windows, qualified = frozen_macro_windows(date(2026, 9, 16))
    expired, expired_qualified = frozen_macro_windows(date(2026, 10, 1))

    assert qualified is True
    assert len(windows) == 1
    assert windows[0][0].astimezone(timezone.utc).isoformat() == "2026-09-16T17:45:00+00:00"
    assert windows[0][1].astimezone(timezone.utc).isoformat() == "2026-09-16T18:15:00+00:00"
    assert "FOMC Decision" in windows[0][2]
    assert expired == []
    assert expired_qualified is False


def test_report_converts_out_of_order_bars_to_explicit_source_failure() -> None:
    trigger = datetime(2026, 8, 24, 14, 30, tzinfo=timezone.utc)
    bars, _ = _five_minute_bars(trigger=trigger, future_closes=[100.4] * 12)
    bars[0], bars[1] = bars[1], bars[0]

    report = build_ground_truth_report(
        bars_by_pair={("SPY", "5m"): bars},
        requested_pairs=[("SPY", "5m")],
        target_date=date(2026, 8, 24),
        data_sources={("SPY", "5m"): "injected_test"},
    )

    assert report["metrics_qualified"] is False
    assert report["producer_healthy"] is False
    assert report["source_failures"][0]["reason"] == "invalid_or_noncausal_bar_sequence"


def test_immature_horizon_is_not_misreported_as_producer_failure() -> None:
    trigger = datetime(2026, 8, 24, 14, 30, tzinfo=timezone.utc)
    bars, _ = _five_minute_bars(trigger=trigger, future_closes=[100.4])

    report = build_ground_truth_report(
        bars_by_pair={("SPY", "5m"): bars},
        requested_pairs=[("SPY", "5m")],
        target_date=date(2026, 8, 24),
        data_sources={("SPY", "5m"): "injected_test"},
    )

    assert report["metrics_qualified"] is False
    assert report["producer_healthy"] is True
    assert report["ground_truth_status"] == "awaiting_horizon_maturity"
    assert report["evidence_pending_count"] == 1


def test_alpaca_acquisition_normalizes_start_time_to_completed_bar_close(monkeypatch) -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"bars": [{"t": "2026-08-24T14:00:00Z", "o": 100, "h": 101, "l": 99, "c": 100.5, "v": 50}], "next_page_token": None}

    seen: dict = {}

    def request_get(url: str, **kwargs):
        seen.update({"url": url, **kwargs})
        return Response()

    monkeypatch.setattr(
        "scripts.build_move_ground_truth._credentials",
        lambda: {"APCA-API-KEY-ID": "not-logged", "APCA-API-SECRET-KEY": "not-logged"},
    )
    bars = fetch_alpaca_bars(
        "SPY",
        "5m",
        start=datetime(2026, 8, 24, tzinfo=timezone.utc),
        end=datetime(2026, 8, 25, tzinfo=timezone.utc),
        feed="iex",
        request_get=request_get,
    )

    assert bars[0]["source_bar_start_ts"] == "2026-08-24T14:00:00Z"
    assert bars[0]["bar_close_ts"] == "2026-08-24T14:05:00Z"
    assert seen["params"]["feed"] == "iex"
    assert seen["params"]["adjustment"] == "raw"


def test_alpaca_acquisition_refuses_futures_without_databento_entitlement() -> None:
    with pytest.raises(RuntimeError, match="futures_feed_not_configured_or_entitled"):
        fetch_alpaca_bars(
            "MES",
            "5m",
            start=datetime(2026, 8, 24, tzinfo=timezone.utc),
            end=datetime(2026, 8, 25, tzinfo=timezone.utc),
            feed="iex",
        )


def test_databento_continuous_futures_are_cost_gated_and_session_labeled() -> None:
    import pandas as pd

    index = pd.date_range("2026-08-23T22:00:00Z", periods=20, freq="1min")
    frame = pd.DataFrame({
        "open": [6500.0 + i for i in range(20)], "high": [6501.0 + i for i in range(20)],
        "low": [6499.0 + i for i in range(20)], "close": [6500.5 + i for i in range(20)],
        "volume": [10 + i for i in range(20)],
    }, index=index)

    class Store:
        def to_df(self):
            return frame

    class Metadata:
        def get_cost(self, **kwargs):
            assert kwargs["dataset"] == "GLBX.MDP3"
            assert kwargs["schema"] == "ohlcv-1m"
            assert kwargs["symbols"] == "ES.v.0"
            assert kwargs["stype_in"] == "continuous"
            return 0.25

        def get_dataset_condition(self, **_kwargs):
            return []

    class Timeseries:
        def get_range(self, **_kwargs):
            return Store()

    class Client:
        metadata = Metadata()
        timeseries = Timeseries()

    result, provenance = fetch_databento_timeframes(
        "ES", start=datetime(2026, 8, 23, 22, 0, tzinfo=timezone.utc),
        end=datetime(2026, 8, 24, 0, 0, tzinfo=timezone.utc), client=Client(), max_cost_usd=1.0,
    )

    assert provenance["provider"] == "databento"
    assert provenance["cost_usd"] == 0.25
    assert provenance["excluded_dataset_condition_dates"] == []
    assert result["5m"][0]["session"] == "ETH"
    assert result["5m"][0]["session_date"] == "2026-08-24"
    assert result["5m"][0]["bar_close_ts"].endswith("22:05:00Z")
    assert result["15m"]


def test_databento_cost_limit_fails_before_download() -> None:
    class Metadata:
        def get_cost(self, **_kwargs):
            return 10.0

    class Timeseries:
        def get_range(self, **_kwargs):
            raise AssertionError("download must not run above the cost limit")

    class Client:
        metadata = Metadata()
        timeseries = Timeseries()

    with pytest.raises(RuntimeError, match="databento_cost_limit_exceeded"):
        fetch_databento_timeframes(
            "MES", start=datetime(2026, 8, 23, tzinfo=timezone.utc),
            end=datetime(2026, 8, 24, tzinfo=timezone.utc), client=Client(), max_cost_usd=1.0,
        )
