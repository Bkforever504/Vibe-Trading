from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.economic_ranking_regret import build_report


DATE = "2026-08-28"
DECISION = "2026-08-28T14:00:00Z"


def _candidate(symbol: str, *, confirmed: bool = True, direction: str = "bullish") -> dict:
    return {
        "symbol": symbol,
        "direction": direction,
        "confirmation_stage": "completed_5m_confirmed" if confirmed else "awaiting_confirmation",
    }


def _snapshot(*, actionable: list[str], ranked: list[dict] | None = None, discovered: list[str] | None = None) -> dict:
    rows = ranked or [_candidate(symbol) for symbol in actionable]
    return {
        "date": DATE,
        "as_of_et": DECISION,
        "all_discovered_symbols": discovered or [row["symbol"] for row in rows],
        "ranked_candidates": rows,
        "filtered_candidates": rows,
        "actionable_ranked_candidates": [_candidate(symbol) for symbol in actionable],
    }


def _outcome(symbol: str, net_r: float, **overrides) -> dict:
    row = {
        "symbol": symbol,
        "decision_at": DECISION,
        "net_r_after_costs": net_r,
        "status": "resolved",
        "execution_evidence_status": "observed_quote_shadow_fill",
        "universe_snapshot_complete": True,
        "fill_assumed": False,
    }
    row.update(overrides)
    return row


def _ground(moves: list[dict]) -> dict:
    return {"date": DATE, "metrics_qualified": True, "moves": moves}


def _move(symbol: str, magnitude: float, *, offset_minutes: int = 5) -> dict:
    return {
        "move_id": f"{DATE}:{symbol}",
        "symbol": symbol,
        "direction": "bullish",
        "move_pct": magnitude,
        "move_start_at": f"2026-08-28T14:{offset_minutes:02d}:00Z",
    }


def test_economic_metrics_use_exact_decision_and_explicit_net_r() -> None:
    snapshot = _snapshot(actionable=["A", "B", "C"])
    report = build_report(
        _ground([_move("B", 4.0)]),
        [snapshot],
        [_outcome("A", -0.5), _outcome("B", 2.0), _outcome("C", 1.0), _outcome("D", 3.0)],
    )

    assert report["metrics_qualified"] is True
    assert report["metrics"]["oracle_vs_selected_net_r_regret"] == {
        "mean": 3.5,
        "median": 3.5,
        "total": 3.5,
        "decision_count": 1,
    }
    assert report["metrics"]["ndcg_at_5"] == pytest.approx(0.369994, abs=1e-6)
    assert report["metrics"]["ndcg_at_10"] == pytest.approx(0.369994, abs=1e-6)
    assert report["metrics"]["magnitude_weighted_recall_at_5"] == 1.0
    assert report["decision_evaluations"][0]["fill_assumed"] is False
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False


def test_stage_decomposition_is_terminal_and_magnitude_weighted() -> None:
    ranked = [
        _candidate("CAPTURED"),
        _candidate("UNCONFIRMED", confirmed=False),
        _candidate("EXECUTION"),
        *[_candidate(f"PAD{i}") for i in range(1, 9)],
        _candidate("RANKMISS"),
    ]
    actionable = ["CAPTURED", *[f"PAD{i}" for i in range(1, 9)], "PAD9", "RANKMISS"]
    snapshot = _snapshot(
        actionable=actionable,
        ranked=ranked,
        discovered=["CAPTURED", "UNCONFIRMED", "EXECUTION", "RANKMISS"],
    )
    outcomes = [_outcome(symbol, float(index)) for index, symbol in enumerate(actionable, 1)]
    moves = [
        _move("MISSING", 5.0),
        _move("UNCONFIRMED", 4.0),
        _move("EXECUTION", 3.0),
        _move("RANKMISS", 2.0),
        _move("CAPTURED", 1.0),
    ]
    report = build_report(_ground(moves), [snapshot], outcomes)

    assert report["stage_decomposition"]["counts"] == {
        "discovery": 1,
        "confirmation": 1,
        "execution": 1,
        "rank": 1,
        "captured": 1,
    }
    assert report["stage_decomposition"]["move_magnitude_pct"] == {
        "discovery": 5.0,
        "confirmation": 4.0,
        "execution": 3.0,
        "rank": 2.0,
        "captured": 1.0,
    }
    assert report["stage_decomposition"]["explicit_positive_net_r_opportunity"]["captured"] == 1.0
    assert report["metrics"]["magnitude_weighted_recall_at_10"] == pytest.approx(1 / 15, abs=1e-6)


@pytest.mark.parametrize(
    "bad_outcome",
    [
        _outcome("A", 1.0, fill_assumed=True),
        _outcome("A", 1.0, premium_inferred_from_underlying=True),
        _outcome("A", 1.0, premium_source="theoretical_model"),
        {"symbol": "A", "decision_at": DECISION, "realized_r": 2.0},
    ],
)
def test_fail_closed_for_missing_or_inferred_fill_evidence(bad_outcome: dict) -> None:
    report = build_report(_ground([_move("A", 1.0)]), [_snapshot(actionable=["A"])], [bad_outcome])

    assert report["metrics_qualified"] is False
    assert report["metrics"]["ndcg_at_5"] is None
    assert report["metrics"]["magnitude_weighted_recall_at_10"] is None
    assert report["metrics"]["oracle_vs_selected_net_r_regret"] is None
    assert "explicit_net_r_outcomes_missing" in report["qualification_issues"]


def test_ground_truth_must_be_frozen_and_qualified() -> None:
    report = build_report(
        {"date": DATE, "metrics_qualified": False, "moves": [_move("A", 1.0)]},
        [_snapshot(actionable=["A"])],
        [_outcome("A", 1.0)],
    )
    assert report["metrics_qualified"] is False
    assert "ground_truth_not_metrics_qualified" in report["qualification_issues"]


def test_direction_specific_frozen_magnitude_is_supported() -> None:
    move = _move("A", 0.0)
    move.pop("move_pct")
    move["magnitude_long"] = 0.75
    report = build_report(_ground([move]), [_snapshot(actionable=["A"])], [_outcome("A", 1.0)])
    assert report["metrics"]["magnitude_weighted_recall_at_5"] == 1.0
    assert report["move_evaluations"][0]["move_magnitude_pct"] == 0.75


def test_cli_paths_are_injectable_and_output_is_shadow_only(tmp_path: Path) -> None:
    ground_path = tmp_path / "ground.json"
    radar_path = tmp_path / "radar.jsonl"
    outcomes_path = tmp_path / "outcomes.jsonl"
    output_path = tmp_path / "report.json"
    ground_path.write_text(json.dumps(_ground([_move("A", 1.0)])), encoding="utf-8")
    radar_path.write_text(json.dumps(_snapshot(actionable=["A"])) + "\n", encoding="utf-8")
    outcomes_path.write_text(json.dumps(_outcome("A", 1.0)) + "\n", encoding="utf-8")

    script = Path(__file__).resolve().parents[2] / "scripts" / "economic_ranking_regret.py"
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--ground-truth",
            str(ground_path),
            "--radar-log",
            str(radar_path),
            "--outcomes",
            str(outcomes_path),
            "--output",
            str(output_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["metrics_qualified"] is True
    assert payload["execution_enabled"] is False
    assert payload["can_submit_orders"] is False
