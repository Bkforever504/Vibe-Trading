from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from scripts import eod_shadow_checkin as checkin


SESSION = date(2026, 8, 24)


def _jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_checkin_uses_session_date_and_summarizes_outcomes(tmp_path: Path, monkeypatch) -> None:
    scout = tmp_path / "scout.jsonl"
    mes = tmp_path / "mes.jsonl"
    _jsonl(
        scout,
        [
            {"event_type": "entry", "session_date": "2026-08-24", "should_enter": True, "symbol": "AAPL", "direction": "long", "grade": 0.88},
            {"event_type": "exit", "session_date": "2026-08-24", "symbol": "AAPL", "outcome": "win", "net_dollar": 150.0, "exit_reason": "t2"},
            {"event_type": "exit", "session_date": "2026-08-23", "symbol": "OLD", "outcome": "loss", "net_dollar": -999.0},
        ],
    )
    _jsonl(
        mes,
        [{"event_type": "exit", "session_date": "2026-08-24", "symbol": "MES", "outcome": "loss", "net_dollar": -50.0, "exit_reason": "stop"}],
    )
    monkeypatch.setattr(checkin, "DATA_DIR", tmp_path)
    monkeypatch.setattr(checkin, "HEALTH_DIR", tmp_path / "health")
    monkeypatch.setattr(checkin, "kill_switch_active", lambda: False)
    report = checkin.build_report(
        session=SESSION,
        scanner_logs={"Scout": scout, "MES": mes},
        heartbeat={"status": "PASS"},
    )
    assert report["status"] == "PASS"
    assert report["totals"]["qualified"] == 1
    assert report["totals"]["wins"] == 1
    assert report["totals"]["losses"] == 1
    assert report["totals"]["net_dollar"] == 100.0
    assert report["best_trade"]["symbol"] == "AAPL"
    assert report["worst_trade"]["symbol"] == "MES"
    message = checkin.format_report(report)
    assert "2026-08-24" in message
    assert "W/L/Flat=1/1/0" in message
    assert "No order authority" in message


def test_checkin_red_alerts_on_halt_or_unhealthy_heartbeat(tmp_path: Path, monkeypatch) -> None:
    health = tmp_path / "health"
    health.mkdir()
    (health / "equity-orb-scout-v2.halt").write_text("halt\n", encoding="utf-8")
    monkeypatch.setattr(checkin, "DATA_DIR", tmp_path)
    monkeypatch.setattr(checkin, "HEALTH_DIR", health)
    monkeypatch.setattr(checkin, "kill_switch_active", lambda: False)
    report = checkin.build_report(
        session=SESSION,
        scanner_logs={},
        heartbeat={"status": "FAIL"},
    )
    assert report["status"] == "ALERT"
    assert report["halted_scanners"] == ["equity-orb-scout-v2"]
    assert "Auto-halted: equity-orb-scout-v2" in checkin.format_report(report)
