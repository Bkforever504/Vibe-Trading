from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import options_grouped_dashboard as dashboard


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_build_dashboard_groups_open_option_pnl(monkeypatch, tmp_path: Path) -> None:
    state_file = tmp_path / "options-trades.json"
    positions_file = tmp_path / "portfolio-concentration.json"
    output_file = tmp_path / "dashboard.json"
    _write_json(
        state_file,
        {
            "trades": [
                {
                    "id": "g1",
                    "label": "Iron Condor [IWM]",
                    "strategy": "iron_condor",
                    "underlying": "IWM",
                    "status": "open",
                    "qty": 2,
                    "net_credit": 0.27,
                    "profit_close_pct": 0.5,
                    "stop_loss_pct": -1.0,
                    "expiry": "2026-08-07",
                    "candidate_confidence": 8,
                    "legs": [
                        "IWM260807P00279000",
                        "IWM260807P00277000",
                        "IWM260807C00317500",
                        "IWM260807C00320000",
                    ],
                }
            ]
        },
    )

    def fake_report(*args, **kwargs):
        return {
            "position_source": {"provider": "fixture"},
            "broker_positions": [
                {"symbol": "IWM260807P00279000", "qty": -2, "unrealized_pl": 12},
                {"symbol": "IWM260807P00277000", "qty": 2, "unrealized_pl": -4},
                {"symbol": "IWM260807C00317500", "qty": -2, "unrealized_pl": 8},
                {"symbol": "IWM260807C00320000", "qty": 2, "unrealized_pl": -2},
            ],
            "reconciliation": {
                "status": "ok",
                "entries_allowed": True,
                "broker_book": {
                    "IWM260807P00279000": -2,
                    "IWM260807P00277000": 2,
                    "IWM260807C00317500": -2,
                    "IWM260807C00320000": 2,
                },
                "group_states": {
                    "g1": {
                        "state": "open",
                        "legs_present": [
                            "IWM260807P00279000",
                            "IWM260807P00277000",
                            "IWM260807C00317500",
                            "IWM260807C00320000",
                        ],
                        "legs_missing": [],
                        "legs_netted": [],
                    }
                },
                "findings": [],
            },
        }

    monkeypatch.setattr(dashboard.options_position_reconciler, "build_report", fake_report)
    report = dashboard.build_dashboard(
        state_file=state_file,
        positions_file=positions_file,
        allow_live=False,
        generated_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
    )
    assert report["status"] == "ok"
    assert report["summary"]["open_groups"] == 1
    assert report["summary"]["total_group_unrealized_pnl"] == 14
    assert report["summary"]["total_broker_option_unrealized_pnl"] == 14
    assert report["summary"]["unattributable_group_pnl_count"] == 0
    row = report["groups"][0]
    assert row["basis"] == 54
    assert row["basis_type"] == "credit"
    assert row["group_unrealized_pnl"] == 14
    assert row["known_leg_unrealized_pnl"] == 14
    assert row["pnl_attribution"] == "complete"
    assert row["group_unrealized_pnl_pct"] == 0.2593
    assert row["distance_to_profit_target_pct"] == 0.2407
    assert row["dte"] == 28
    assert row["flags"] == []

    written = dashboard.write_dashboard(report, output_file)
    assert json.loads(written.read_text(encoding="utf-8"))["provider"] == "options_grouped_dashboard"


def test_dashboard_flags_manual_review_and_stop_threshold(monkeypatch, tmp_path: Path) -> None:
    state_file = tmp_path / "options-trades.json"
    positions_file = tmp_path / "portfolio-concentration.json"
    _write_json(
        state_file,
        {
            "trades": [
                {
                    "id": "g2",
                    "label": "Put Spread [IWM]",
                    "strategy": "put_spread",
                    "status": "open",
                    "qty": 1,
                    "net_credit": 0.20,
                    "profit_close_pct": 0.5,
                    "stop_loss_pct": -1.0,
                    "expiry": "2026-07-11",
                    "legs": ["IWM260711P00279000", "IWM260711P00276000"],
                }
            ]
        },
    )

    def fake_report(*args, **kwargs):
        return {
            "position_source": {"provider": "fixture"},
            "broker_positions": [
                {"symbol": "IWM260711P00279000", "qty": -1, "unrealized_pl": -25},
            ],
            "reconciliation": {
                "status": "review_required",
                "entries_allowed": False,
                "broker_book": {
                    "IWM260711P00279000": -1,
                    "IWM260711P00276000": 1,
                },
                "group_states": {
                    "g2": {
                        "state": "manual_review",
                        "legs_present": ["IWM260711P00279000"],
                        "legs_missing": ["IWM260711P00276000"],
                        "legs_netted": [],
                    }
                },
                "findings": ["manual review fixture"],
            },
        }

    monkeypatch.setattr(dashboard.options_position_reconciler, "build_report", fake_report)
    report = dashboard.build_dashboard(
        state_file=state_file,
        positions_file=positions_file,
        allow_live=False,
        generated_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
    )
    row = report["groups"][0]
    assert report["status"] == "review_required"
    assert report["summary"]["total_broker_option_unrealized_pnl"] == -25
    assert report["summary"]["unattributable_group_pnl_count"] == 1
    assert row["group_unrealized_pnl"] is None
    assert row["known_leg_unrealized_pnl"] == -25
    assert row["pnl_attribution"] == "blocked_by_missing_or_netted_legs"
    assert "manual_review" in row["flags"]
    assert "missing_legs" in row["flags"]
    assert "expiry_near" in row["flags"]
