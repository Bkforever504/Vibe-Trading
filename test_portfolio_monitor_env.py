import json
from pathlib import Path


def test_portfolio_guard_reads_thresholds_dynamically(monkeypatch) -> None:
    from strategies import portfolio_guard

    monkeypatch.setenv("PORTFOLIO_MAX_DAILY_LOSS_DOLLARS", "900")
    monkeypatch.setenv("PORTFOLIO_SOFT_WARNING_DOLLARS", "450")
    monkeypatch.setenv("PORTFOLIO_EMERGENCY_KILL_DOLLARS", "1800")
    monkeypatch.setenv("PORTFOLIO_SOFT_BREACH_POLLS_REQUIRED", "3")

    assert portfolio_guard.portfolio_max_daily_loss_dollars() == 900
    assert portfolio_guard.portfolio_soft_warning_dollars() == 450
    assert portfolio_guard.portfolio_emergency_kill_dollars() == 1800
    assert portfolio_guard.portfolio_soft_breach_polls_required() == 3


def test_portfolio_monitor_soft_warning_alerts_once(monkeypatch, tmp_path: Path) -> None:
    from strategies import portfolio_monitor

    alerts: list[str] = []
    monkeypatch.setattr(portfolio_monitor, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(portfolio_monitor, "PORTFOLIO_KILL_FILE", tmp_path / "kill.json")
    monkeypatch.setattr(portfolio_monitor, "_fetch_daily_pnl", lambda: -525.0)
    monkeypatch.setattr(portfolio_monitor, "_fetch_account_equity", lambda: 88000.0)
    monkeypatch.setattr(portfolio_monitor, "_discord_alert", alerts.append)
    monkeypatch.setattr(portfolio_monitor, "portfolio_soft_warning_dollars", lambda: 500.0)
    monkeypatch.setattr(portfolio_monitor, "portfolio_max_daily_loss_dollars", lambda: 750.0)
    monkeypatch.setattr(portfolio_monitor, "portfolio_emergency_kill_dollars", lambda: 1500.0)
    monkeypatch.setattr(portfolio_monitor, "portfolio_soft_breach_polls_required", lambda: 2)

    assert portfolio_monitor.main() == 0
    assert portfolio_monitor.main() == 0

    assert len(alerts) == 1
    assert "Portfolio soft warning" in alerts[0]
    assert not (tmp_path / "kill.json").exists()


def test_portfolio_monitor_hard_kill_requires_consecutive_polls(monkeypatch, tmp_path: Path) -> None:
    from strategies import portfolio_monitor

    alerts: list[str] = []
    kill_file = tmp_path / "kill.json"
    monkeypatch.setattr(portfolio_monitor, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(portfolio_monitor, "PORTFOLIO_KILL_FILE", kill_file)
    monkeypatch.setattr(portfolio_monitor, "_fetch_daily_pnl", lambda: -800.0)
    monkeypatch.setattr(portfolio_monitor, "_fetch_account_equity", lambda: 88000.0)
    monkeypatch.setattr(portfolio_monitor, "_fetch_positions_summary", lambda: [
        {"symbol": "SPY260629C00738000", "qty": "5", "market_value": 1205.0, "unrealized_pl": 535.0}
    ])
    monkeypatch.setattr(portfolio_monitor, "_discord_alert", alerts.append)
    monkeypatch.setattr(portfolio_monitor, "portfolio_soft_warning_dollars", lambda: 500.0)
    monkeypatch.setattr(portfolio_monitor, "portfolio_max_daily_loss_dollars", lambda: 750.0)
    monkeypatch.setattr(portfolio_monitor, "portfolio_emergency_kill_dollars", lambda: 1500.0)
    monkeypatch.setattr(portfolio_monitor, "portfolio_soft_breach_polls_required", lambda: 2)

    assert portfolio_monitor.main() == 0
    assert not kill_file.exists()

    assert portfolio_monitor.main() == 2
    payload = json.loads(kill_file.read_text(encoding="utf-8"))

    assert payload["reason"] == "max_daily_loss"
    assert payload["daily_pnl_dollars"] == -800.0
    assert payload["details"]["breach_count"] == 2
    assert payload["details"]["positions"][0]["symbol"] == "SPY260629C00738000"
