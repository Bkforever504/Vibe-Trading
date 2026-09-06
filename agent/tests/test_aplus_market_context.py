from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from scripts import aplus_market_context as context


ET = ZoneInfo("America/New_York")


def _row(
    minute: int,
    *,
    above_vwap: float,
    es_bps: float = 0.0,
    nq_bps: float = 0.0,
    index_bps: float = 0.0,
    vol_z: float = 0.0,
    advancing: float = 55.0,
    declining: float = 45.0,
    highs: float = 2.0,
    lows: float = 1.0,
    hour: int = 9,
) -> dict:
    timestamp = datetime(2026, 8, 31, hour, minute, tzinfo=ET)
    return {
        "timestamp": timestamp.isoformat(),
        "es_return_1m_bps": es_bps,
        "nq_return_1m_bps": nq_bps,
        "index_return_1m_bps": index_bps,
        "realized_vol_z": vol_z,
        "breadth_above_vwap_pct": above_vwap,
        "advancing_dollar_volume": advancing,
        "declining_dollar_volume": declining,
        "new_intraday_highs": highs,
        "new_intraday_lows": lows,
        "overnight_es_return_bps": 18.0,
        "overnight_nq_return_bps": 22.0,
        "spy_premarket_gap_bps": 15.0,
        "qqq_premarket_gap_bps": 25.0,
    }


def _normalized(rows: list[dict]) -> list[dict]:
    normalized, errors = context._normalize_market_rows(rows)
    assert errors == []
    return normalized


def test_breadth_acceleration_requires_multivariate_causal_agreement() -> None:
    rows = _normalized([
        _row(20, above_vwap=40.0, advancing=52, declining=48, highs=1, lows=1),
        _row(25, above_vwap=41.0, advancing=57, declining=43, highs=2, lows=1),
        _row(
            30, above_vwap=45.0, es_bps=5.0, nq_bps=7.0,
            advancing=70, declining=30, highs=6, lows=1,
        ),
    ])

    result = context.breadth_futures_context(rows, 2)

    assert result["status"] == "available"
    assert result["state"] == "risk_on_participation_accelerating"
    assert result["breadth_acceleration_pp"] == 3.0
    assert result["agreement_count"] == 3
    assert result["legacy_pairwise_rule_reactivated"] is False
    assert "no_leader_to_lagged_instrument_trade_rule" in result["distinction_from_rejected_pairwise"]


def test_breadth_challenger_fails_closed_on_missing_or_stale_history() -> None:
    rows = _normalized([
        _row(0, above_vwap=40.0),
        _row(5, above_vwap=41.0),
        _row(30, above_vwap=45.0, es_bps=5.0, nq_bps=5.0),
    ])
    stale = context.breadth_futures_context(rows, 2)
    assert stale["status"] == "unavailable"
    assert stale["reason"] == "stale_or_noncausal_history"

    rows = _normalized([
        _row(20, above_vwap=40.0),
        _row(25, above_vwap=41.0),
        _row(30, above_vwap=45.0),
    ])
    del rows[-1]["nq_return_1m_bps"]
    missing = context.breadth_futures_context(rows, 2)
    assert missing["status"] == "unavailable"
    assert "nq_return_1m_bps" in missing["missing_fields"]


def test_online_change_point_abstains_and_widens_after_abrupt_shift() -> None:
    detector = context.OnlineChangePoint()
    stable = [detector.observe((0.0, 0.0, 0.0)) for _ in range(8)]

    assert stable[-1]["abstain_from_aplus"] is False
    assert stable[-1]["uncertainty_widening_factor"] < 1.1

    shifted = detector.observe((8.0, 8.0, 8.0))

    assert shifted["posterior_change_probability"] >= context.BOCPD_CHANGE_THRESHOLD
    assert shifted["most_likely_run_length"] == 0
    assert shifted["abstain_from_aplus"] is True
    assert shifted["abstention_reason"] == "change_probability_high"
    assert shifted["uncertainty_widening_factor"] > stable[-1]["uncertainty_widening_factor"]
    assert shifted["calibration_locally_applicable"] is False


def test_missing_change_point_features_force_abstention_without_updating_model() -> None:
    report = context.build_report(
        [{"timestamp": datetime(2026, 8, 31, 10, 0, tzinfo=ET).isoformat()}],
        generated_at=datetime(2026, 8, 31, 15, 0, tzinfo=ZoneInfo("UTC")),
    )

    change = report["contexts"][0]["change_point"]
    assert change["status"] == "unavailable"
    assert change["abstain_from_aplus"] is True
    assert change["calibration_locally_applicable"] is False
    assert change["uncertainty_widening_factor"] == 2.0


def test_opening_context_uses_only_normalized_auction_rows_known_by_decision() -> None:
    decision = _normalized([_row(28, above_vwap=45.0)])[0]
    auction, errors = context._normalize_auction_rows([
        {
            "timestamp": datetime(2026, 8, 31, 9, 26, tzinfo=ET).isoformat(),
            "symbol": "QQQ", "paired_shares": 800, "imbalance_shares": 200,
            "imbalance_direction": "buy",
        },
        {
            "timestamp": datetime(2026, 8, 31, 9, 29, tzinfo=ET).isoformat(),
            "symbol": "QQQ", "paired_shares": 100, "imbalance_shares": 900,
            "imbalance_direction": "sell",
        },
    ])
    assert errors == []

    result = context.opening_auction_context(decision, auction)

    assert result["status"] == "available"
    assert result["state"] == "aligned_positive_opening_inventory"
    assert result["signed_auction_imbalance_ratio"] == 0.2
    assert result["latest_auction_source_timestamp"].endswith("13:26:00Z")
    assert result["future_auction_rows_used"] is False


def test_auction_is_unavailable_when_missing_and_not_applicable_after_open() -> None:
    opening = _normalized([_row(30, above_vwap=45.0)])[0]
    missing = context.opening_auction_context(opening, [])
    assert missing["status"] == "unavailable"
    assert missing["reason"] == "no_normalized_auction_rows_known_at_decision"

    after_open = _normalized([_row(40, above_vwap=45.0)])[0]
    outside = context.opening_auction_context(after_open, [])
    assert outside == {
        "status": "not_applicable",
        "reason": "outside_opening_window",
        "authority": "shadow_context_only",
    }


def test_report_is_sorted_auditable_and_has_no_order_authority() -> None:
    rows = [
        _row(30, above_vwap=45.0, es_bps=5, nq_bps=6, advancing=70, declining=30, highs=6, lows=1),
        _row(20, above_vwap=40.0),
        _row(25, above_vwap=41.0, advancing=57, declining=43, highs=2, lows=1),
    ]
    auction = [{
        "timestamp": datetime(2026, 8, 31, 9, 26, tzinfo=ET).isoformat(),
        "symbol": "QQQ", "paired_shares": 800, "imbalance_shares": 200,
        "imbalance_direction": "buy",
    }]

    report = context.build_report(rows, auction, generated_at=datetime(2026, 8, 31, 14, 0, tzinfo=ZoneInfo("UTC")))

    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["preregistration"]["parameter_search_performed"] is False
    assert report["coverage"]["context_rows"] == 3
    assert report["coverage"]["breadth_futures_available"] == 1
    assert report["contexts"] == sorted(report["contexts"], key=lambda row: row["timestamp"])
    assert all(row["inputs_known_at_or_before_timestamp"] is True for row in report["contexts"])
    assert all(row["execution_enabled"] is False and row["can_submit_orders"] is False for row in report["contexts"])


def test_cli_accepts_injected_json_inputs_and_writes_report(tmp_path, monkeypatch) -> None:
    market_path = tmp_path / "market.json"
    auction_path = tmp_path / "auction.json"
    output_path = tmp_path / "report.json"
    market_path.write_text(json.dumps({"market_rows": [
        _row(20, above_vwap=40.0),
        _row(25, above_vwap=41.0),
        _row(30, above_vwap=45.0, es_bps=5, nq_bps=6, advancing=70, declining=30, highs=6, lows=1),
    ]}), encoding="utf-8")
    auction_path.write_text(json.dumps({"auction_rows": [{
        "timestamp": datetime(2026, 8, 31, 9, 26, tzinfo=ET).isoformat(),
        "symbol": "QQQ", "paired_shares": 800, "imbalance_shares": 200,
        "imbalance_direction": "buy",
    }]}), encoding="utf-8")
    monkeypatch.setattr("sys.argv", [
        "aplus_market_context.py", "--market-input", str(market_path),
        "--auction-input", str(auction_path), "--output", str(output_path),
    ])

    assert context.main() == 0
    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert written["provider"] == "aplus_market_context_shadow"
    assert written["execution_enabled"] is False
    assert written["contexts"][-1]["breadth_futures"]["status"] == "available"


def test_naive_timestamp_is_rejected_fail_closed() -> None:
    report = context.build_report([{"timestamp": "2026-08-31T09:30:00"}])
    assert report["contexts"] == []
    assert report["operational_health"] == "unavailable"
    assert "missing_or_naive_timestamp" in report["data_quality"]["validation_errors"][0]
