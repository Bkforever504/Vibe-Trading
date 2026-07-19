from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts import bot_behavior_regression_watchdog as watchdog


def _json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_watchdog_detects_gate_dominance_and_setup_mismatch(tmp_path: Path) -> None:
    decisions = tmp_path / "decisions.jsonl"
    trades = tmp_path / "trades.json"
    shadow = tmp_path / "shadow.json"
    consensus = tmp_path / "consensus.json"
    rows = [{
        "ts": f"2026-07-15T1{index}:00:00Z",
        "reason": "shadow_consensus_block",
        "symbol": "SPY",
        "strategy": "0dte",
        "details": {
            "right": "PUT",
            "blockers": ["adaptive_flip_evidence_does_not_confirm_bullish_direction", "credit_spread_too_narrow"],
        },
    } for index in range(5)]
    _jsonl(decisions, rows)
    _json(trades, [])
    _json(shadow, {})
    _json(consensus, {})

    report = watchdog.build_report(
        decision_log=decisions,
        trades_path=trades,
        shadow_path=shadow,
        consensus_path=consensus,
        now=datetime(2026, 7, 15, 20, tzinfo=timezone.utc),
    )

    assert report["status"] == "alert"
    assert report["shadow_consensus_block_share"] == 1.0
    assert report["setup_mismatch_count"] == 5
    assert {row["code"] for row in report["alerts"]} >= {
        "consensus_gate_dominates_qualified_path", "setup_agnostic_gate_mismatch",
    }


def test_watchdog_flags_positive_shadow_stand_aside_for_review(tmp_path: Path) -> None:
    decisions = tmp_path / "decisions.jsonl"
    trades = tmp_path / "trades.json"
    shadow = tmp_path / "shadow.json"
    consensus = tmp_path / "consensus.json"
    _jsonl(decisions, [])
    _json(trades, [])
    _json(shadow, {"by_symbol": {"AAPL": {"out_of_sample_count": 8, "out_of_sample_expectancy_return_pct": 12.5}}})
    _json(consensus, {"decisions": [{"symbol": "AAPL", "recommendation": "stand_aside", "blockers": ["weak_shadow_pnl_evidence"]}]})

    report = watchdog.build_report(
        decision_log=decisions,
        trades_path=trades,
        shadow_path=shadow,
        consensus_path=consensus,
        now=datetime(2026, 7, 15, 20, tzinfo=timezone.utc),
    )

    assert report["status"] == "watch"
    assert report["positive_shadow_suppression"][0]["symbol"] == "AAPL"


def test_watchdog_never_has_execution_authority(tmp_path: Path) -> None:
    decisions = tmp_path / "decisions.jsonl"
    trades = tmp_path / "trades.json"
    shadow = tmp_path / "shadow.json"
    consensus = tmp_path / "consensus.json"
    _jsonl(decisions, [])
    _json(trades, [])
    _json(shadow, {})
    _json(consensus, {})

    report = watchdog.build_report(
        decision_log=decisions,
        trades_path=trades,
        shadow_path=shadow,
        consensus_path=consensus,
    )

    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False


def test_discord_alert_sends_once_then_deduplicates(tmp_path: Path) -> None:
    sent: list[tuple[str, str]] = []
    report = {
        "status": "alert",
        "generated_at": "2026-07-15T20:00:00Z",
        "window_days": 7,
        "decision_count": 42,
        "qualified_path_count": 42,
        "shadow_consensus_block_count": 42,
        "shadow_consensus_block_share": 1.0,
        "setup_mismatch_count": 41,
        "business_days_without_close": 6,
        "alerts": [{"code": "setup_agnostic_gate_mismatch", "severity": "high"}],
    }
    sender = lambda url, message: sent.append((url, message))

    first = watchdog.notify_discord(
        report,
        state_path=tmp_path / "state.json",
        webhook="https://discord.invalid/test",
        sender=sender,
    )
    second = watchdog.notify_discord(
        report,
        state_path=tmp_path / "state.json",
        webhook="https://discord.invalid/test",
        sender=sender,
    )

    assert first["status"] == "sent"
    assert second["status"] == "deduplicated"
    assert len(sent) == 1
    assert "BOT BEHAVIOR WATCHDOG: ALERT" in sent[0][1]


def test_watch_notification_is_opt_in(tmp_path: Path) -> None:
    report = {"status": "watch", "generated_at": "2026-07-15T20:00:00Z", "alerts": []}

    result = watchdog.notify_discord(
        report,
        state_path=tmp_path / "state.json",
        webhook="https://discord.invalid/test",
        sender=lambda *_: (_ for _ in ()).throw(AssertionError("must not send")),
        notify_watch=False,
    )

    assert result["status"] == "not_eligible"
    assert result["sent"] is False


def test_discord_failure_is_recorded_without_leaking_webhook(tmp_path: Path) -> None:
    report = {"status": "alert", "generated_at": "2026-07-15T20:00:00Z", "alerts": []}

    result = watchdog.notify_discord(
        report,
        state_path=tmp_path / "state.json",
        webhook="https://discord.invalid/secret",
        sender=lambda *_: (_ for _ in ()).throw(TimeoutError("secret endpoint")),
    )

    assert result["status"] == "error"
    assert result["error"] == "TimeoutError"
    assert "webhook" not in result


def test_watchdog_mismatch_alert_decays_after_repair(tmp_path: Path) -> None:
    decisions = tmp_path / "decisions.jsonl"
    trades = tmp_path / "trades.json"
    shadow = tmp_path / "shadow.json"
    consensus = tmp_path / "consensus.json"
    rows = [{
        "ts": f"2026-07-15T1{index}:00:00Z",
        "reason": "shadow_consensus_block",
        "symbol": "SPY",
        "strategy": "0dte",
        "details": {
            "right": "PUT",
            "blockers": ["adaptive_flip_evidence_does_not_confirm_bullish_direction"],
        },
    } for index in range(3)]
    _jsonl(decisions, rows)
    _json(trades, [])
    _json(shadow, {})
    _json(consensus, {})

    report = watchdog.build_report(
        decision_log=decisions,
        trades_path=trades,
        shadow_path=shadow,
        consensus_path=consensus,
        now=datetime(2026, 7, 21, 20, tzinfo=timezone.utc),
    )

    mismatch_alerts = [
        row for row in report["alerts"] if row["code"] == "setup_agnostic_gate_mismatch"
    ]
    assert len(mismatch_alerts) == 1
    alert = mismatch_alerts[0]
    assert alert["severity"] == "decaying"
    assert alert["latest_mismatch_ts"] == "2026-07-15T12:00:00Z"
    assert alert["business_days_since_latest_mismatch"] == 4
    assert report["status"] != "alert"


def test_watchdog_fresh_mismatch_stays_high_severity(tmp_path: Path) -> None:
    decisions = tmp_path / "decisions.jsonl"
    trades = tmp_path / "trades.json"
    shadow = tmp_path / "shadow.json"
    consensus = tmp_path / "consensus.json"
    _jsonl(decisions, [{
        "ts": "2026-07-21T14:00:00Z",
        "reason": "shadow_consensus_block",
        "symbol": "SPY",
        "strategy": "0dte",
        "details": {
            "right": "PUT",
            "blockers": ["adaptive_flip_evidence_does_not_confirm_bullish_direction"],
        },
    }])
    _json(trades, [])
    _json(shadow, {})
    _json(consensus, {})

    report = watchdog.build_report(
        decision_log=decisions,
        trades_path=trades,
        shadow_path=shadow,
        consensus_path=consensus,
        now=datetime(2026, 7, 21, 20, tzinfo=timezone.utc),
    )

    mismatch_alerts = [
        row for row in report["alerts"] if row["code"] == "setup_agnostic_gate_mismatch"
    ]
    assert len(mismatch_alerts) == 1
    assert mismatch_alerts[0]["severity"] == "high"
    assert report["status"] == "alert"
