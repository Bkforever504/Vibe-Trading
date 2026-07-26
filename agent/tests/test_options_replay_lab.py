from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research import options_replay_lab as replay


def test_candidate_expiries_buckets() -> None:
    # 2026-07-22 is a Wednesday.
    buckets = replay.candidate_expiries("2026-07-22")

    assert buckets["0dte"] == ["2026-07-22"]
    assert buckets["1dte"] == ["2026-07-23"]
    assert buckets["3_7dte"][0] == "2026-07-27"  # Sat/Sun skipped
    assert all(replay.date.fromisoformat(d).weekday() < 5 for d in buckets["3_7dte"])


def test_spread_calibration_falls_back_below_minimum_samples() -> None:
    thin = [{"contract": "SPY260717C00747000", "quote": {"bid": 1.00, "ask": 1.04}}] * 3

    result = replay.calibrate_spread(thin)

    assert result["source"] == "frozen_fallback"
    assert result["rel_spread"] == replay.SPREAD_FALLBACK_REL


def test_spread_calibration_uses_p75_of_valid_spy_samples() -> None:
    samples = [
        {"contract": "SPY260717C00747000", "quote": {"bid": 1.00, "ask": 1.00 + 0.01 * i}}
        for i in range(1, 13)
    ]
    samples.append({"contract": "QQQ260717C00500000", "quote": {"bid": 1.0, "ask": 2.0}})
    samples.append({"contract": "SPY260717P00700000", "quote": {"bid": 0, "ask": 0.05}})

    result = replay.calibrate_spread(samples)

    assert result["source"] == "forward_nbbo_p75"
    assert result["samples"] == 12
    assert 0.05 < result["rel_spread"] < 0.12


def _bars_for(day: str, prices: dict[str, float]) -> list[dict]:
    # ET times converted to UTC (July -> DST, UTC-4).
    out = []
    for hhmm, price in prices.items():
        hour, minute = (int(x) for x in hhmm.split(":"))
        out.append({
            "t": f"{day}T{hour + 4:02d}:{minute:02d}:00Z",
            "o": price, "h": price, "l": price, "c": price, "v": 100,
        })
    return out


def test_replay_signal_applies_spread_floor_and_commissions() -> None:
    signal = {
        "date": "2026-07-22",
        "direction": "bull",
        "underlying_entry": 733.4,
        "underlying_return_60m_bps": 5.0,
        "variants": ["ltf_only", "daily_aligned"],
    }

    def fetch(occ: str, day: str):
        if occ.startswith("SPY260722C00733000"):
            return _bars_for(day, {"12:00": 1.00, "12:59": 1.30})
        return []

    result = replay.replay_signal(signal, fetch, half_spread_rel=0.04)

    outcome = result["0dte"]
    assert outcome["status"] == "filled"
    assert outcome["occ"] == "SPY260722C00733000"
    # buy = 1.00 + max(1.00*0.02, 0.02) = 1.02 ; sell = 1.30 - max(0.026, 0.02)
    assert outcome["buy"] == 1.02
    assert outcome["sell"] == 1.274
    expected_pnl = (1.274 - 1.02) * 100 - replay.COMMISSION_ROUND_TRIP
    assert abs(outcome["pnl_dollars_per_contract"] - round(expected_pnl, 2)) < 1e-9
    assert result["1dte"]["status"] == "unavailable"


def test_replay_signal_skips_when_entry_bar_missing() -> None:
    signal = {
        "date": "2026-07-22",
        "direction": "bear",
        "underlying_entry": 733.0,
        "underlying_return_60m_bps": -3.0,
        "variants": ["ltf_only"],
    }

    def fetch(occ: str, day: str):
        return _bars_for(day, {"12:05": 1.0, "12:50": 1.1})

    result = replay.replay_signal(signal, fetch, half_spread_rel=0.04)

    assert result["0dte"]["status"] == "skipped_missing_bars"


def test_summarize_separates_variants_and_counts_unfilled() -> None:
    rows = [
        {
            "variants": ["ltf_only", "daily_aligned"],
            "0dte": {"status": "filled", "return_pct": 10.0},
            "1dte": {"status": "unavailable"},
            "3_7dte": {"status": "filled", "return_pct": -5.0},
        },
        {
            "variants": ["ltf_only"],
            "0dte": {"status": "skipped_missing_bars"},
            "1dte": {"status": "filled", "return_pct": 4.0},
            "3_7dte": {"status": "filled", "return_pct": 6.0},
        },
    ]

    summary = replay.summarize(rows)

    assert summary["ltf_only"]["0dte"]["signals"] == 2
    assert summary["ltf_only"]["0dte"]["filled"] == 1
    assert summary["daily_aligned"]["0dte"]["signals"] == 1
    assert summary["ltf_only"]["3_7dte"]["mean_return_pct"] == 0.5
