from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import loop_closure_report as report


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_builds_trade_explanations_with_exit_quality(tmp_path: Path) -> None:
    flip_path = tmp_path / "flip-trades.json"
    postmortem_path = tmp_path / "postmortem.json"
    _write(flip_path, [
        {
            "id": "t1",
            "status": "closed",
            "entry_date": "2026-07-06",
            "exit_date": "2026-07-06",
            "symbol": "SPY",
            "strategy": "bull_trend",
            "right": "CALL",
            "option_symbol": "SPY260706C00750000",
            "contracts": 5,
            "entry_price": 0.78,
            "exit_price": 0.915,
            "best_pnl_pct": 66.03,
            "exit_reason": "PROFIT PROTECT +17.3% (best +66.0%)",
            "pnl": 67.5,
            "catalyst": "VWAP/50EMA bull trend 9/10",
        }
    ])
    _write(postmortem_path, {
        "date": "2026-07-06",
        "postmortems": [
            {
                "bot": "flip_bot",
                "trade_id": "t1",
                "pnl_explanation": {
                    "primary_driver": "price moved in the option direction, then faded",
                    "exit_quality": {
                        "best_pnl_pct": 66.03,
                        "exit_return_pct": 17.31,
                        "giveback_pct": 48.72,
                        "capture_efficiency": 0.262,
                    },
                    "next_action": "tighten profit-capture cadence",
                },
            }
        ],
    })

    built = report.build_report(
        day="2026-07-06",
        flip_trades_path=flip_path,
        postmortem_path=postmortem_path,
        options_trades_path=tmp_path / "missing-options.json",
        options_decisions_path=tmp_path / "missing-decisions.jsonl",
        grades_path=tmp_path / "missing-grades.json",
        cheap_asymmetry_path=tmp_path / "missing-cheap.json",
        learning_path=tmp_path / "missing-learning.json",
    )

    trade = built["trade_explanations"][0]
    assert trade["bot"] == "flip_bot"
    assert trade["symbol"] == "SPY"
    assert trade["pnl"] == 67.5
    assert trade["exit_quality"]["giveback_pct"] == 48.72
    assert trade["lesson"] == "tighten profit-capture cadence"
    assert trade["loop_state"] == "lesson_needed"


def test_loop_closure_recomputes_loss_quality_instead_of_trusting_stale_capture(tmp_path: Path) -> None:
    flip_path = tmp_path / "flip-trades.json"
    postmortem_path = tmp_path / "postmortem.json"
    _write(flip_path, [{
        "id": "loss-after-green", "status": "closed", "entry_date": "2026-07-16",
        "exit_date": "2026-07-16", "symbol": "SPY", "strategy": "0dte", "right": "CALL",
        "entry_price": 1.0, "exit_price": 0.6217, "best_pnl_pct": 12.61,
        "exit_reason": "STOP LOSS -37.8%", "pnl": -37.83,
    }])
    _write(postmortem_path, {
        "date": "2026-07-16",
        "postmortems": [{
            "bot": "flip_bot", "trade_id": "loss-after-green",
            "pnl_explanation": {
                "exit_quality": {"capture_efficiency": -3.0, "giveback_pct": 50.44},
                "next_action": "tighten profit-capture cadence",
            },
        }],
    })

    built = report.build_report(
        day="2026-07-16", flip_trades_path=flip_path, postmortem_path=postmortem_path,
        options_trades_path=tmp_path / "missing-options.json",
        options_decisions_path=tmp_path / "missing-decisions.jsonl",
        grades_path=tmp_path / "missing-grades.json",
        cheap_asymmetry_path=tmp_path / "missing-cheap.json",
        learning_path=tmp_path / "missing-learning.json",
    )
    trade = built["trade_explanations"][0]

    assert trade["exit_quality"]["capture_efficiency"] is None
    assert trade["exit_quality"]["giveback_pct"] is None
    assert trade["exit_quality"]["exit_quality_classification"] == "stop_loss_after_favorable_excursion"
    assert trade["lesson"] == "review entry filter and regime conflict before next same-direction trade"
    assert trade["loop_state"] == "entry_filter_review"


def test_loss_uses_appropriate_postmortem_action_and_becomes_open_lesson(tmp_path: Path) -> None:
    flip_path = tmp_path / "flip-trades.json"
    postmortem_path = tmp_path / "postmortem.json"
    _write(flip_path, [{
        "id": "fast-stop", "status": "closed", "entry_date": "2026-07-17",
        "exit_date": "2026-07-17", "symbol": "SPY", "strategy": "bull_trend", "right": "CALL",
        "entry_price": 1.32, "exit_price": 0.725, "best_pnl_pct": 0.0,
        "exit_reason": "STOP LOSS -45.1%", "pnl": -119.0,
    }])
    _write(postmortem_path, {
        "date": "2026-07-17",
        "postmortems": [{
            "bot": "flip_bot", "trade_id": "fast-stop", "pnl_explanation": {
                "primary_driver": "entry/regime failure: the option never moved favorably and hit stop within 10 minutes",
                "next_action": "require ORB/retest proof or cleaner regime",
            },
        }],
    })

    built = report.build_report(
        day="2026-07-17", flip_trades_path=flip_path, postmortem_path=postmortem_path,
        options_trades_path=tmp_path / "missing-options.json",
        options_decisions_path=tmp_path / "missing-decisions.jsonl",
        grades_path=tmp_path / "missing-grades.json",
        cheap_asymmetry_path=tmp_path / "missing-cheap.json",
        learning_path=tmp_path / "missing-learning.json",
    )

    trade = built["trade_explanations"][0]
    assert trade["lesson"] == "require ORB/retest proof or cleaner regime"
    assert built["summary"]["open_lesson_count"] == 1
    lessons = report.canonical_lessons(built)
    assert lessons[0]["status"] == "open"
    assert lessons[0]["next_stage"] == "counterfactual_shadow_trial"


def test_lesson_ledger_is_deduplicated_by_trade(tmp_path: Path) -> None:
    built = {
        "generated_at": "2026-07-17T20:00:00Z",
        "trade_explanations": [{
            "date": "2026-07-17", "bot": "flip_bot", "trade_id": "t1",
            "symbol": "SPY", "strategy": "bull_trend", "direction": "CALL",
            "pnl": -119.0, "primary_driver": "entry/regime failure",
            "lesson": "require ORB/retest proof", "loop_state": "entry_filter_review",
        }],
    }
    ledger_path = tmp_path / "lessons.jsonl"
    report_path = tmp_path / "lessons.json"

    first = report.write_lesson_ledger(built, ledger_path, report_path)
    second = report.write_lesson_ledger(built, ledger_path, report_path)

    assert first["new_count"] == 1
    assert second["new_count"] == 0
    assert second["lesson_count"] == 1
    assert second["open_count"] == 1
    assert ledger_path.read_text(encoding="utf-8").count("\n") == 1


def test_collects_no_trade_reasons_from_options_decision_log(tmp_path: Path) -> None:
    decisions = tmp_path / "options-decisions.jsonl"
    decisions.write_text(
        "\n".join([
            json.dumps({"ts": "2026-07-06T14:45:00Z", "symbol": "IWM", "strategy": "both", "action": "skip", "reason": "underlying_exposure_cap"}),
            json.dumps({"ts": "2026-07-06T14:46:00Z", "symbol": "SPY", "strategy": "ps", "action": "skip", "reason": "trend_filter_below_20sma"}),
            json.dumps({"ts": "2026-07-05T14:46:00Z", "symbol": "AAPL", "strategy": "ps", "action": "skip", "reason": "old"}),
        ]),
        encoding="utf-8",
    )

    built = report.build_report(
        day="2026-07-06",
        flip_trades_path=tmp_path / "missing-flip.json",
        postmortem_path=tmp_path / "missing-postmortem.json",
        options_trades_path=tmp_path / "missing-options.json",
        options_decisions_path=decisions,
        grades_path=tmp_path / "missing-grades.json",
        cheap_asymmetry_path=tmp_path / "missing-cheap.json",
        learning_path=tmp_path / "missing-learning.json",
    )

    by_symbol = {row["symbol"]: row for row in built["no_trade_explanations"]}
    assert by_symbol["IWM"]["primary_reason"] == "underlying_exposure_cap"
    assert by_symbol["SPY"]["bot"] == "iwm_options_bot"
    assert built["summary"]["no_trade_count"] == 2


def test_scores_scanner_promotion_status_and_blockers(tmp_path: Path) -> None:
    grades_path = tmp_path / "grades.json"
    cheap_path = tmp_path / "cheap.json"
    learning_path = tmp_path / "learning.json"
    _write(grades_path, {
        "items": [
            {"name": "Cheap Asymmetry Scanner", "sample_count": 9, "signal_count": 4, "evidence_score": 78, "promotion_ready": False, "warnings": ["not_enough_samples"]},
            {"name": "Market Force Score", "sample_count": 31, "signal_count": 11, "evidence_score": 83, "promotion_ready": True, "warnings": []},
        ]
    })
    _write(cheap_path, {"summary": {"goal_match_count": 0}, "top_candidates": [{"symbol": "AAPL", "best_return_pct": 538.7}]})
    _write(learning_path, {"lessons": [{"severity": "high", "type": "capture_gap"}]})

    built = report.build_report(
        day="2026-07-06",
        flip_trades_path=tmp_path / "missing-flip.json",
        postmortem_path=tmp_path / "missing-postmortem.json",
        options_trades_path=tmp_path / "missing-options.json",
        options_decisions_path=tmp_path / "missing-decisions.jsonl",
        grades_path=grades_path,
        cheap_asymmetry_path=cheap_path,
        learning_path=learning_path,
    )

    by_name = {row["name"]: row for row in built["promotion_scoreboard"]}
    assert by_name["Market Force Score"]["close_to_live_score"] >= 80
    assert by_name["Market Force Score"]["promotion_state"] == "review_candidate"
    assert by_name["Cheap Asymmetry Scanner"]["promotion_state"] == "blocked"
    assert "no_repeated_goal_matches" in by_name["Cheap Asymmetry Scanner"]["blockers"]
    assert "unresolved_high_severity_lessons" in built["next_day_gate"]["blockers"]


def test_write_report_log_and_handoff(tmp_path: Path) -> None:
    built = report.build_report(day="2026-07-06")
    report_path = tmp_path / "loop-closure-report.json"
    log_path = tmp_path / "loop_closure_report_log.jsonl"
    handoff_path = tmp_path / "CLAUDE_HANDOFF_LOOP_CLOSURE.md"

    report.write_report(built, report_path)
    report.append_log(built, log_path)
    report.write_handoff(built, handoff_path)

    assert json.loads(report_path.read_text(encoding="utf-8"))["provider"] == "loop_closure_report"
    assert log_path.read_text(encoding="utf-8").count("\n") == 1
    handoff = handoff_path.read_text(encoding="utf-8")
    assert "Claude Code Handoff" in handoff
    assert "scanner -> decision -> trade/no-trade" in handoff


def test_registry_contains_read_only_entry() -> None:
    registry = json.loads((ROOT / "research" / "signal_registry.json").read_text(encoding="utf-8"))
    entry = next(item for item in registry["signals"] if item["id"] == "loop_closure_report")

    assert entry["script"] == "scripts/loop_closure_report.py"
    assert entry["execution_enabled"] is False
    assert entry["can_submit_orders"] is False
