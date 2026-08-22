from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research import options_nbbo_curriculum as curriculum


def test_default_quote_path_uses_licensed_nbbo_capture() -> None:
    assert curriculum.DEFAULT_QUOTES_PATH.name == "options_nbbo_candidate_quotes.jsonl"
    assert curriculum.DEFAULT_QUOTES_PATH.parent.name == "databento"
    assert curriculum.DEFAULT_QUOTES_PATH != curriculum.DEFAULT_CANDIDATES_PATH


def _ts(day: int, seconds: int = 0) -> datetime:
    return datetime(2025, 1, day, 15, 0, seconds, tzinfo=timezone.utc)


def _candidate(day: int = 2, *, candidate_id: str = "candidate-1") -> dict:
    start = _ts(day)
    return {
        "type": "candidate",
        "candidate_id": candidate_id,
        "created_at": start.isoformat(),
        "contract_selected_at": start.isoformat(),
        "evaluation_end_at": (start + timedelta(seconds=30)).isoformat(),
        "strategy": "call_spread",
        "expiry": "2025-02-21",
        "effective_qty": 1,
        "max_risk_per_contract": 402.0,
        "profit_close_pct": 0.50,
        "stop_loss_pct": -1.0,
        "legs": [
            {"symbol": f"SPY250221C00600{day:03d}", "side": "sell", "ratio_qty": 1},
            {"symbol": f"SPY250221C00605{day:03d}", "side": "buy", "ratio_qty": 1},
        ],
    }


def _quote(symbol: str, observed: datetime, bid: float, ask: float, **overrides) -> dict:
    row = {
        "symbol": symbol,
        "observed_at": observed.isoformat(),
        "quote_timestamp": observed.isoformat(),
        "bid": bid,
        "ask": ask,
        "quote_scope": "synthetic_opra_nbbo",
    }
    row.update(overrides)
    return row


def _winning_tape(candidate: dict) -> list[dict]:
    start = datetime.fromisoformat(candidate["created_at"])
    end = datetime.fromisoformat(candidate["evaluation_end_at"])
    short, long = (leg["symbol"] for leg in candidate["legs"])
    return [
        _quote(short, start, 1.20, 1.22),
        _quote(long, start, 0.20, 0.22),
        _quote(short, end, 0.35, 0.37),
        _quote(long, end, 0.06, 0.07),
    ]


def _iron_fly_candidate() -> dict:
    start = _ts(2)
    return {
        "type": "candidate",
        "candidate_id": "iron-fly-1",
        "created_at": start.isoformat(),
        "contract_selected_at": start.isoformat(),
        "evaluation_end_at": (start + timedelta(seconds=30)).isoformat(),
        "strategy": "iron_fly",
        "expiry": "2025-02-21",
        "effective_qty": 1,
        "max_risk_per_contract": 256.0,
        "profit_close_pct": 0.50,
        "stop_loss_pct": -1.0,
        "legs": [
            {"symbol": "SPY250221P00595000", "side": "buy", "ratio_qty": 1},
            {"symbol": "SPY250221P00600000", "side": "sell", "ratio_qty": 1},
            {"symbol": "SPY250221C00600000", "side": "sell", "ratio_qty": 1},
            {"symbol": "SPY250221C00605000", "side": "buy", "ratio_qty": 1},
        ],
    }


def test_credit_spread_uses_bid_ask_execution_and_per_leg_fees() -> None:
    candidate = _candidate()
    quotes = curriculum.normalize_quote_rows(_winning_tape(candidate))

    result = curriculum.replay_candidate(candidate, curriculum.build_quote_index(quotes))

    assert result["status"] == "resolved"
    assert result["reason"] == "profit_target"
    assert result["entry_credit"] == 0.98
    assert result["closing_debit"] == 0.31
    assert result["gross_pnl_before_fees"] == 67.0
    assert result["base_fees"] == 2.64
    assert result["pnl_base"] == 64.36
    assert result["pnl_double_fees"] == 61.72


def test_iron_fly_replays_with_four_leg_executable_quotes() -> None:
    candidate = _iron_fly_candidate()
    start = datetime.fromisoformat(candidate["created_at"])
    end = datetime.fromisoformat(candidate["evaluation_end_at"])
    long_put, short_put, short_call, long_call = (
        leg["symbol"] for leg in candidate["legs"]
    )
    rows = [
        _quote(long_put, start, 0.25, 0.27),
        _quote(short_put, start, 1.50, 1.52),
        _quote(short_call, start, 1.45, 1.47),
        _quote(long_call, start, 0.22, 0.24),
        _quote(long_put, end, 0.08, 0.09),
        _quote(short_put, end, 0.43, 0.45),
        _quote(short_call, end, 0.38, 0.40),
        _quote(long_call, end, 0.07, 0.08),
    ]

    result = curriculum.replay_candidate(
        candidate,
        curriculum.build_quote_index(curriculum.normalize_quote_rows(rows)),
    )

    assert result["status"] == "resolved"
    assert result["strategy"] == "iron_fly"
    assert result["reason"] == "profit_target"
    assert result["entry_credit"] == 2.44
    assert result["closing_debit"] == 0.70
    assert result["base_fees"] == 5.28
    assert result["pnl_base"] == 168.72


def test_future_contract_selection_is_rejected() -> None:
    candidate = _candidate()
    candidate["contract_selected_at"] = (
        datetime.fromisoformat(candidate["created_at"]) + timedelta(seconds=1)
    ).isoformat()
    result = curriculum.replay_candidate(
        candidate,
        curriculum.build_quote_index(curriculum.normalize_quote_rows(_winning_tape(candidate))),
    )
    assert result["status"] == "unavailable"
    assert result["reason"] == "contract_selection_not_point_in_time"


def test_non_occ_contract_is_rejected_before_quote_replay() -> None:
    candidate = _candidate()
    candidate["legs"][0]["symbol"] = "NOT-AN-OCC-SYMBOL"

    result = curriculum.replay_candidate(candidate, {})

    assert result["status"] == "unavailable"
    assert result["reason"] == "invalid_occ_contract"


def test_quote_timestamp_after_observation_is_never_used() -> None:
    candidate = _candidate()
    rows = _winning_tape(candidate)
    rows[0]["quote_timestamp"] = (
        datetime.fromisoformat(rows[0]["observed_at"]) + timedelta(seconds=1)
    ).isoformat()
    result = curriculum.replay_candidate(
        candidate,
        curriculum.build_quote_index(curriculum.normalize_quote_rows(rows)),
    )
    assert result["status"] == "unavailable"
    assert result["reason"] == "lookahead_quote"


def test_non_nbbo_and_stale_quotes_fail_closed() -> None:
    candidate = _candidate()
    rows = _winning_tape(candidate)
    rows[0]["quote_scope"] = "alpaca_indicative_modified_not_opra_nbbo"
    non_nbbo = curriculum.replay_candidate(
        candidate,
        curriculum.build_quote_index(curriculum.normalize_quote_rows(rows)),
    )
    assert non_nbbo["status"] == "unavailable"
    assert non_nbbo["reason"] == "non_nbbo_scope"

    rows = _winning_tape(candidate)
    rows[0]["quote_timestamp"] = (
        datetime.fromisoformat(rows[0]["observed_at"]) - timedelta(seconds=3)
    ).isoformat()
    stale = curriculum.replay_candidate(
        candidate,
        curriculum.build_quote_index(curriculum.normalize_quote_rows(rows)),
    )
    assert stale["status"] == "unavailable"
    assert stale["reason"] == "stale_quote"


def test_crossed_wide_and_skewed_markets_are_vetoed() -> None:
    stamp = _ts(2)
    symbols = ["A", "B"]
    config = curriculum.OptionsNbboConfig()
    crossed = curriculum.normalize_quote_rows([
        _quote("A", stamp, 1.2, 1.1), _quote("B", stamp, 0.2, 0.22),
    ])
    assert curriculum.executable_snapshot(curriculum.build_quote_index(crossed), symbols, stamp, config)[1] == "invalid_or_crossed_market"
    wide = curriculum.normalize_quote_rows([
        _quote("A", stamp, 0.5, 1.0), _quote("B", stamp, 0.2, 0.22),
    ])
    assert curriculum.executable_snapshot(curriculum.build_quote_index(wide), symbols, stamp, config)[1] == "quote_width_veto"
    skewed = curriculum.normalize_quote_rows([
        _quote("A", stamp, 1.0, 1.02),
        _quote("B", stamp, 0.2, 0.22, quote_timestamp=(stamp - timedelta(seconds=3)).isoformat()),
    ])
    loose_age = curriculum.OptionsNbboConfig(max_quote_age_seconds=5.0)
    assert curriculum.executable_snapshot(curriculum.build_quote_index(skewed), symbols, stamp, loose_age)[1] == "inter_leg_quote_skew"


def test_no_exit_quote_does_not_invent_option_result_from_underlying() -> None:
    candidate = _candidate()
    candidate["underlying_return_bps"] = 500.0
    start = datetime.fromisoformat(candidate["created_at"])
    short, long = (leg["symbol"] for leg in candidate["legs"])
    rows = [_quote(short, start, 1.2, 1.22), _quote(long, start, 0.2, 0.22)]
    result = curriculum.replay_candidate(
        candidate,
        curriculum.build_quote_index(curriculum.normalize_quote_rows(rows)),
    )
    assert result["status"] == "unavailable"
    assert "pnl_base" not in result


def test_polling_sensitivity_exposes_target_window_missed_by_five_minutes() -> None:
    candidate = _candidate()
    start = datetime.fromisoformat(candidate["created_at"])
    candidate["evaluation_end_at"] = (start + timedelta(minutes=6)).isoformat()
    short, long = (leg["symbol"] for leg in candidate["legs"])
    rows = [
        _quote(short, start, 1.20, 1.22),
        _quote(long, start, 0.20, 0.22),
        _quote(short, start + timedelta(minutes=1), 0.33, 0.35),
        _quote(long, start + timedelta(minutes=1), 0.06, 0.07),
        _quote(short, start + timedelta(minutes=2), 0.78, 0.80),
        _quote(long, start + timedelta(minutes=2), 0.10, 0.11),
        _quote(short, start + timedelta(minutes=5), 0.78, 0.80),
        _quote(long, start + timedelta(minutes=5), 0.10, 0.11),
    ]

    result = curriculum.replay_candidate(
        candidate,
        curriculum.build_quote_index(curriculum.normalize_quote_rows(rows)),
    )

    sensitivity = result["monitoring_cadence_sensitivity"]
    assert result["reason"] == "profit_target"
    assert sensitivity["one_minute"]["reason"] == "profit_target"
    assert sensitivity["five_minute"]["status"] == "open_through_available_data"
    assert sensitivity["legacy_thirty_minute"]["status"] == "open_through_available_data"


def test_locked_holdout_is_separate_and_can_fail_positive_development() -> None:
    candidates = []
    quotes = []
    for index in range(50):
        day = datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(days=index)
        candidate = _candidate(candidate_id=f"candidate-{index}")
        candidate["created_at"] = day.replace(hour=15).isoformat()
        candidate["contract_selected_at"] = candidate["created_at"]
        candidate["evaluation_end_at"] = (day.replace(hour=15) + timedelta(seconds=30)).isoformat()
        candidates.append(candidate)
        tape = _winning_tape(candidate)
        if index >= 40:
            end = datetime.fromisoformat(candidate["evaluation_end_at"])
            short, long = (leg["symbol"] for leg in candidate["legs"])
            tape[-2:] = [_quote(short, end, 2.1, 2.2), _quote(long, end, 0.06, 0.07)]
        quotes.extend(tape)
    report = curriculum.run_curriculum(candidates, quotes)
    assert report["development"]["summary"]["base"]["expectancy_dollars"] > 0
    assert report["locked_holdout"]["resolved_count"] == 10
    assert report["locked_holdout"]["summary"]["base"]["expectancy_dollars"] < 0
    assert report["review_gate"]["checks"]["holdout_base_positive"] is False
    assert report["review_gate"]["passed"] is False
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False


def test_empty_quote_history_reports_coverage_unavailable() -> None:
    report = curriculum.run_curriculum([_candidate()], [])
    assert report["status"] == "coverage_unavailable"
    assert report["resolved_count"] == 0
    assert report["review_gate"]["passed"] is False
    assert report["execution_model"]["underlying_return_substitution_allowed"] is False


def test_curriculum_lookahead_audit_counts_rejected_future_quotes() -> None:
    candidate = _candidate()
    rows = _winning_tape(candidate)
    rows[0]["quote_timestamp"] = (
        datetime.fromisoformat(rows[0]["observed_at"]) + timedelta(seconds=1)
    ).isoformat()

    report = curriculum.run_curriculum([candidate], rows)

    assert report["lookahead_audit"]["violation_count"] == 1
    assert report["lookahead_audit"]["passed"] is False
    assert report["review_gate"]["checks"]["no_lookahead_violations"] is False
