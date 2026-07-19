"""Tests for scripts/options_position_reconciler.py (read-only reconciler)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import options_position_reconciler as opr


def _write_incident_fixtures(tmp_path: Path) -> tuple[Path, Path]:
    state_file = tmp_path / "options-trades.json"
    state_file.write_text(json.dumps({
        "trades": [
            {
                "id": "1733badd-f177-4b51-92fb-14e759280934",
                "label": "Iron Condor [IWM]",
                "strategy": "iron_condor",
                "status": "closed",
                "closed_at": "2026-07-07T14:45:03Z",
                "qty": 2,
                "legs": [
                    "IWM260807P00279000",
                    "IWM260807P00277000",
                    "IWM260807C00317500",
                    "IWM260807C00320000",
                ],
            },
            {
                "id": "d72ded80-b97f-4fb4-a6a7-d3c0d77ddc51",
                "label": "Iron Condor [IWM]",
                "strategy": "iron_condor",
                "status": "open",
                "qty": 2,
                "legs": [
                    "IWM260807P00277000",
                    "IWM260807P00275000",
                    "IWM260807C00313000",
                    "IWM260807C00315000",
                ],
            },
        ]
    }), encoding="utf-8")

    positions_file = tmp_path / "portfolio-concentration.json"
    positions_file.write_text(json.dumps({
        "timestamp": "2026-07-09T16:05:02Z",
        "concentration": {
            "positions": [
                {"symbol": "IWM260807C00313000", "qty": -2},
                {"symbol": "IWM260807C00315000", "qty": 2},
                {"symbol": "IWM260807C00317500", "qty": -2},
                {"symbol": "IWM260807C00320000", "qty": 2},
                {"symbol": "IWM260807P00275000", "qty": 2},
                {"symbol": "IWM260807P00279000", "qty": -2},
            ]
        },
    }), encoding="utf-8")
    return state_file, positions_file


def test_reconciler_report_is_read_only_and_explains_incident(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    state_file, positions_file = _write_incident_fixtures(tmp_path)

    report = opr.build_report(state_file, positions_file, allow_live=False)

    assert report["mode"] == "read_only"
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False

    rec = report["reconciliation"]
    assert rec["status"] == "review_required"
    assert rec["entries_allowed"] is False
    assert "IWM260807P00277000" in rec["netted_symbols"]
    assert "1733badd-f177-4b51-92fb-14e759280934" in rec["closed_groups_still_open"]
    assert rec["unexplained_residual"] == {}

    plan = report["proposed_repair_plan"]
    assert plan["requires_kenny_approval"] is True
    actions = {step["action"] for step in plan["steps"]}
    assert "restore_group_to_manual_review" in actions
    assert "acknowledge_netted_legs" in actions


def test_reconciler_clean_state_produces_no_repair_steps(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"trades": [
        {
            "id": "ps1",
            "strategy": "put_spread",
            "status": "open",
            "qty": 3,
            "legs": ["IWM260709P00289000", "IWM260709P00286000"],
        }
    ]}), encoding="utf-8")
    positions_file = tmp_path / "conc.json"
    positions_file.write_text(json.dumps({
        "timestamp": "2026-07-09T16:05:02Z",
        "concentration": {"positions": [
            {"symbol": "IWM260709P00289000", "qty": -3},
            {"symbol": "IWM260709P00286000", "qty": 3},
        ]},
    }), encoding="utf-8")

    report = opr.build_report(state_file, positions_file, allow_live=False)
    rec = report["reconciliation"]
    assert rec["status"] == "ok"
    assert rec["entries_allowed"] is True
    plan = report["proposed_repair_plan"]
    assert plan["requires_kenny_approval"] is False
    assert plan["steps"][0]["action"] == "none"


def test_reconciler_fails_closed_without_position_source(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"trades": []}), encoding="utf-8")

    report = opr.build_report(state_file, tmp_path / "missing.json", allow_live=False)
    assert report["reconciliation"]["entries_allowed"] is False
    assert report["execution_enabled"] is False


def test_reconciler_main_writes_report_atomically(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    state_file, positions_file = _write_incident_fixtures(tmp_path)
    output = tmp_path / "out" / "reconciliation.json"

    code = opr.main([
        "--state-file", str(state_file),
        "--positions-file", str(positions_file),
        "--output", str(output),
        "--no-live",
        "--print",
    ])
    assert code == 0
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["provider"] == "options_position_reconciler"
    assert data["can_submit_orders"] is False


def test_reconciler_main_loads_agent_env_without_overriding_shell(tmp_path: Path, monkeypatch) -> None:
    state_file, positions_file = _write_incident_fixtures(tmp_path)
    output = tmp_path / "reconciliation.json"
    calls = []

    monkeypatch.setattr(opr, "load_dotenv", lambda *args, **kwargs: calls.append((args, kwargs)))

    code = opr.main([
        "--state-file", str(state_file),
        "--positions-file", str(positions_file),
        "--output", str(output),
        "--no-live",
    ])

    assert code == 0
    assert calls == [((), {"dotenv_path": opr.ENV_FILE, "override": False})]
