from __future__ import annotations

from scripts import generate_dashboard as dashboard
from scripts.flip_bot_learning_report import _trailing_regime


def _trade(day: str, pnl: float) -> dict:
    return {"entry_date": day, "exit_date": day, "exit_at": f"{day}T16:00:00Z", "pnl": pnl}


def test_trailing_regime_does_not_hide_a_recent_negative_cluster() -> None:
    # Strong historical results must not grant permission when the current
    # completed sample is losing.
    trades = [
        _trade("2026-06-29", 500), _trade("2026-06-30", 450),
        _trade("2026-07-01", 400), _trade("2026-07-02", 350),
        _trade("2026-07-06", -100), _trade("2026-07-07", -120),
        _trade("2026-07-08", -130), _trade("2026-07-09", -140),
        _trade("2026-07-10", -150),
    ]

    recent = _trailing_regime(trades, 5)

    assert recent["net_pnl"] == -640
    assert recent["status"] == "degraded_pause_new_entries"


def test_options_pnl_provenance_never_calls_missing_fill_zero() -> None:
    assert dashboard.option_pnl_provenance({"pnl": 0}) == "reconciled"
    assert dashboard.option_pnl_provenance({"net_credit": 0.5, "closing_reason": "profit target hit: +50% of credit"}) == "estimated_from_exit_rule"
    assert dashboard.option_pnl_provenance({"net_credit": 0.5, "closing_reason": ""}) == "unreconciled"


def test_dashboard_labels_unreconciled_options_outcomes() -> None:
    html = dashboard.render_daily_pnl({
        "flip_trades": [],
        "options_state": {"trades": [{
            "status": "closed", "closed_at": "2026-07-07T15:00:00Z",
            "underlying": "AAPL", "net_credit": 0.87,
        }]},
    })

    assert "UNRECONCILED" in html
    assert "Excluded from P/L until reconciled" in html
