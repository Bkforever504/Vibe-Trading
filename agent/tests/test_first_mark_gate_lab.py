import json
from pathlib import Path

from research import flip_filter_lab
from research import first_mark_gate_lab as lab


def _write_lifecycle(
    path: Path,
    *,
    lifecycle_id: str,
    date: str,
    first_signal: float,
    first_bid: float,
    exit_bid: float,
) -> None:
    rows = [
        {
            "lifecycle_id": lifecycle_id,
            "date": date,
            "symbol": "SPY",
            "scanned_at": f"{date}T14:30:00Z",
            "event_type": "shadow_entry",
            "entry_price_est": 1.0,
            "selection_ask": 1.0,
        },
        {
            "lifecycle_id": lifecycle_id,
            "date": date,
            "symbol": "SPY",
            "scanned_at": f"{date}T14:35:00Z",
            "event_type": "shadow_mark",
            "mark_price": 1.0 + first_signal / 100.0,
            "selection_bid": first_bid,
            "return_pct_at_mark": first_signal,
            "mark_reason": "lifecycle_mark",
        },
        {
            "lifecycle_id": lifecycle_id,
            "date": date,
            "symbol": "SPY",
            "scanned_at": f"{date}T15:00:00Z",
            "event_type": "shadow_exit",
            "mark_price": exit_bid,
            "selection_bid": exit_bid,
            "return_pct_at_mark": (exit_bid - 1.0) * 100.0,
            "mark_reason": "episode_horizon",
        },
    ]
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def test_first_mark_gate_replay_uses_ask_to_bid_and_frozen_thresholds(tmp_path: Path) -> None:
    candidates = tmp_path / "candidates.jsonl"
    _write_lifecycle(
        candidates,
        lifecycle_id="2026-08-10|SPY|CALL|0dte|09:30",
        date="2026-08-10",
        first_signal=-1.0,
        first_bid=0.90,
        exit_bid=0.50,
    )
    _write_lifecycle(
        candidates,
        lifecycle_id="2026-08-11|SPY|CALL|0dte|09:30",
        date="2026-08-11",
        first_signal=2.0,
        first_bid=1.00,
        exit_bid=1.20,
    )

    report = lab.build_report(candidates_path=candidates, fee_pct=0.0)
    rows = {row["policy"]: row for row in report["policies_full_corpus"]}

    assert rows["baseline_no_gate"]["post_fee"]["expectancy_pct"] == -15.0
    assert rows["gate_mark1_any_negative"]["post_fee"]["expectancy_pct"] == 5.0
    assert rows["gate_mark1_any_negative"]["post_fee"]["gate_fired_count"] == 1
    assert rows["gate_mark1_below_minus5"]["post_fee"]["gate_fired_count"] == 0
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["evidence_label"] == "exploratory_post_discovery_consumed_corpus"
    assert report["first_mark_green_review"]["request_paper_approval"] is False


def test_flip_filter_lab_recognizes_first_observation_shadow_exit(tmp_path: Path) -> None:
    candidates = tmp_path / "candidates.jsonl"
    rows = [
        {
            "lifecycle_id": "2026-08-12|QQQ|PUT|0dte|10:00",
            "date": "2026-08-12",
            "symbol": "QQQ",
            "scanned_at": "2026-08-12T14:30:00Z",
            "event_type": "shadow_entry",
            "entry_price_est": 1.0,
        },
        {
            "lifecycle_id": "2026-08-12|QQQ|PUT|0dte|10:00",
            "date": "2026-08-12",
            "symbol": "QQQ",
            "scanned_at": "2026-08-12T14:35:00Z",
            "event_type": "shadow_exit",
            "mark_price": 0.9,
            "selection_bid": 0.88,
            "return_pct_at_mark": -10.0,
            "mark_reason": "first_mark_momentum_not_confirmed",
        },
    ]
    candidates.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    lives = flip_filter_lab.load_lifecycles(candidates)

    assert len(lives) == 1
    assert lives[0].first_mark_return_pct == -10.0
