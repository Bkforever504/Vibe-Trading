from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import review_portfolio_kill_switch as review


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _fixture(tmp_path: Path, *, paper: bool = True) -> tuple[Path, Path, Path]:
    kill = tmp_path / "PORTFOLIO_KILL_SWITCH.json"
    reports = tmp_path / "reports"
    env = tmp_path / ".env"
    env.write_text(f"ALPACA_PAPER={'true' if paper else 'false'}\n", encoding="utf-8")
    _write(kill, {"status": "killed", "manual_reset_required": True, "max_daily_loss_dollars": 750, "triggered_at": "2026-07-07T15:05:16Z", "reason": "max_daily_loss"})
    _write(reports / "portfolio-concentration.json", {"date": "2026-07-13", "account": {"day_change": -32}, "concentration": {"risk_level": "normal"}})
    _write(reports / "options-position-reconciliation.json", {"reconciliation": {"unexplained_residual": {}, "netted_symbols": ["P277"]}})
    _write(reports / "signal-stack-health.json", {"summary": {"ok": 45, "error": 0, "missing": 0, "stale": 0}})
    _write(reports / "execution-gate-audit.json", {"passed": True, "issue_count": 0})
    _write(reports / "market-catalyst-calendar.json", {"upcoming": [{"date": "2026-07-14", "events": [{"name": "CPI Release"}], "allowed_playbooks": ["stand_aside", "directional_long_post_confirmation"]}]})
    return kill, reports, env


def test_eligible_paper_reset_archives_original(tmp_path: Path, monkeypatch) -> None:
    kill, reports, env = _fixture(tmp_path)
    monkeypatch.delenv("ALPACA_PAPER", raising=False)
    result = review.build_review(kill_path=kill, report_dir=reports, env_path=env, today="2026-07-13")

    archive = review.archive_reset(result, kill, approved_by="Kenny", reason="Reviewed recovered paper account")

    assert result["eligible_for_paper_reset"] is True
    assert result["reset_performed"] is True
    assert not kill.exists()
    assert json.loads(archive.read_text(encoding="utf-8"))["triggered_at"] == "2026-07-07T15:05:16Z"


def test_live_account_reset_is_denied(tmp_path: Path, monkeypatch) -> None:
    kill, reports, env = _fixture(tmp_path, paper=False)
    monkeypatch.delenv("ALPACA_PAPER", raising=False)
    result = review.build_review(kill_path=kill, report_dir=reports, env_path=env, today="2026-07-13")

    with pytest.raises(RuntimeError, match="denied"):
        review.archive_reset(result, kill, approved_by="Kenny", reason="test")

    assert result["eligible_for_paper_reset"] is False
    assert kill.exists()
