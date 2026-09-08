from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from scripts import mnq_smt_family_runner as family
from scripts import shadow_alert_runner as alerts
from scripts import shadow_outcome_resolver as resolver
from scripts import shadow_system_heartbeat as heartbeat


EXPECTED = {
    "mnq-smt-cisd-fvg-v1": (
        "scripts.mnq_smt_cisd_fvg_v1_shadow",
        "mnq_smt_cisd_fvg_v1_shadow_log.jsonl",
    ),
    "mnq-pdl-rejection-v1": (
        "scripts.mnq_pdl_rejection_v1_shadow",
        "mnq_pdl_rejection_v1_shadow_log.jsonl",
    ),
    "mnq-smt-only-v1": (
        "scripts.mnq_smt_only_v1_shadow",
        "mnq_smt_only_v1_shadow_log.jsonl",
    ),
    "mnq-cisd-only-v1": (
        "scripts.mnq_cisd_only_v1_shadow",
        "mnq_cisd_only_v1_shadow_log.jsonl",
    ),
}


def test_all_four_ablation_scanners_and_ledgers_are_registered() -> None:
    assert family.SCANNER_IDS == tuple(EXPECTED)
    for scanner, (module, ledger) in EXPECTED.items():
        assert alerts.SCANNERS[scanner]["module"] == module
        assert alerts.SCANNERS[scanner]["notify_empty"] is False
        assert ledger in resolver.LEDGER_NAMES


def test_empty_frequent_scan_suppresses_discord_but_qualified_entry_notifies(
    tmp_path: Path, monkeypatch
) -> None:
    log_path = tmp_path / "shadow.jsonl"
    rows: list[dict] = []

    def run_entry(*, log_path: Path) -> int:
        with log_path.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")
        return 0

    fake_module = SimpleNamespace(LOG_PATH=log_path, run_entry=run_entry, run_resolve=lambda **_kwargs: 0)
    monkeypatch.setattr(alerts.importlib, "import_module", lambda _name: fake_module)
    monkeypatch.setattr(alerts, "record_success", lambda _scanner: {"halted": False})
    monkeypatch.setattr(resolver, "run_once", lambda: {"resolved_count": 0})
    sent: list[str] = []

    quiet = alerts.run_guarded("mnq-smt-only-v1", "entry", notify=lambda message: sent.append(message) or {})
    assert quiet["status"] == "completed"
    assert quiet["notification"]["status"] == "suppressed_no_action"
    assert sent == []

    rows.append(
        {
            "event_type": "entry",
            "plan_id": "fixture-1",
            "should_enter": True,
            "symbol": "MNQ",
            "direction": "short",
            "entry_price": 100,
            "stop_price": 102,
            "t1_price": 98,
            "t2_price": 96,
        }
    )
    qualified = alerts.run_guarded("mnq-smt-only-v1", "entry", notify=lambda message: sent.append(message) or {})
    assert qualified["status"] == "completed"
    assert len(sent) == 1
    assert "MNQ SHORT" in sent[0]


def test_family_runner_continues_after_one_ablation_fails(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_run(scanner: str, mode: str, **_kwargs) -> dict:
        calls.append((scanner, mode))
        return {"status": "exception" if scanner == family.SCANNER_IDS[0] else "completed", "exit_code": 1}

    monkeypatch.setattr(family, "run_guarded", fake_run)
    report = family.run_family("cycle")
    assert calls == [
        *((scanner, "entry") for scanner in family.SCANNER_IDS),
        *((scanner, "resolve") for scanner in family.SCANNER_IDS),
    ]
    assert len(report["runs"]) == 8
    assert report["status"] == "partial_failure"
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False


def test_scheduler_is_one_low_authority_five_minute_rth_family_task() -> None:
    root = Path(__file__).resolve().parents[2]
    registration = (root / "scripts" / "register_mnq_smt_family_shadow_task.ps1").read_text(encoding="utf-8")
    runner = (root / "scripts" / "run_mnq_smt_family_shadow.ps1").read_text(encoding="utf-8")
    assert "--with purgedcv==0.1.6" in runner
    assert "--with arch==8.0.0" in runner
    assert "--with tsbootstrap==0.7.2" in runner
    assert '(Get-TimeZone).Id -ne "Central Standard Time"' in registration
    assert '-TaskPath "\\VibeTrade\\"' in registration
    assert 'MnqSmtCisdFamilyShadow' in registration
    assert '-At "08:35"' in registration
    assert 'PT5M' in registration and 'PT7H' in registration
    assert '-MultipleInstances IgnoreNew' in registration
    assert '-StartWhenAvailable' in registration
    assert '-RunLevel Limited' in registration
    assert "mnq_smt_family_runner.py" in runner
    assert 'ValidateSet("entry", "resolve", "cycle")' in runner
    assert '"cycle"' in runner
    assert ("\\VibeTrade\\", "MnqSmtCisdFamilyShadow") in heartbeat.EXPECTED_TASKS


def test_delayed_databento_regrader_is_cost_capped_and_monitored() -> None:
    root = Path(__file__).resolve().parents[2]
    registration = (root / "scripts" / "register_mnq_smt_databento_regrader_task.ps1").read_text(encoding="utf-8")
    runner = (root / "scripts" / "run_mnq_smt_family_databento_regrader.ps1").read_text(encoding="utf-8")
    assert '-At "00:45"' in registration
    assert '-RunLevel Limited' in registration
    assert '-MultipleInstances IgnoreNew' in registration
    assert '--max-daily-cost 5.00' in runner
    assert 'KILL_SWITCH' in runner
    assert ("\\VibeTrade\\", "MnqSmtDatabentoRegrade") in heartbeat.EXPECTED_TASKS
