from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_ironbeam_settings_reports_missing_credentials(monkeypatch) -> None:
    from strategies.ironbeam_market_data import IronbeamSettings

    for key in ("IRONBEAM_USERNAME", "IRONBEAM_PASSWORD", "IRONBEAM_API_KEY"):
        monkeypatch.delenv(key, raising=False)

    settings = IronbeamSettings.from_env()

    assert settings.missing_fields() == [
        "IRONBEAM_USERNAME",
        "IRONBEAM_PASSWORD",
        "IRONBEAM_API_KEY",
    ]


def test_ironbeam_front_month_symbol_rolls_quarterly_contracts() -> None:
    from strategies.ironbeam_market_data import current_front_month_symbol

    assert current_front_month_symbol("MNQ", today=date(2026, 6, 10)) == "MNQM6"
    assert current_front_month_symbol("MNQ", today=date(2026, 6, 24)) == "MNQU6"
    assert current_front_month_symbol("@NQ", today=date(2026, 12, 20)) == "NQH7"


def test_ironbeam_readiness_blocks_without_funded_api_access(monkeypatch) -> None:
    from strategies.ironbeam_market_data import IronbeamSettings, readiness_report

    monkeypatch.setenv("IRONBEAM_USERNAME", "demo-user")
    monkeypatch.setenv("IRONBEAM_PASSWORD", "demo-pass")
    monkeypatch.setenv("IRONBEAM_API_KEY", "demo-key")
    monkeypatch.setenv("IRONBEAM_FUNDED_ACCOUNT_CONFIRMED", "false")

    report = readiness_report(IronbeamSettings.from_env())

    assert report["ready"] is False
    assert "funded account not confirmed" in report["blockers"]
