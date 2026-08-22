from __future__ import annotations

import pandas as pd

from research import topstep_mes_reopen_drift_lab as baseline
from research import topstep_mes_reopen_stop_lab as stopped
from research import topstep_mes_reopen_weekday_holdout as weekday
from research import topstep_mes_reopen_weekday_bbo_holdout as bbo


def test_summarize_uses_fixed_contract_equity_drawdown() -> None:
    result = baseline.summarize(pd.Series([10.0, -30.0, 5.0, 20.0]))

    assert result["trades"] == 4
    assert result["avg_pnl"] == 1.25
    assert result["profit_factor"] == 1.1667
    assert result["max_drawdown"] == -30.0


def test_baseline_report_is_research_only_and_fails_drawdown_gate(monkeypatch) -> None:
    dates = pd.to_datetime(
        ["2024-01-02"] * 100 + ["2025-01-02"] * 100 + ["2026-01-02"] * 75
    )
    pnl = [20.0, -200.0] * 137 + [20.0]
    trades = pd.DataFrame(
        {
            "exit_date": dates,
            "base_pnl": pnl,
            "stress_1_pnl": [value - 2.5 for value in pnl],
            "stress_2_pnl": [value - 5.0 for value in pnl],
            "weekday": ["Monday"] * len(dates),
        }
    )
    monkeypatch.setattr(baseline, "load_round_trips", lambda _path: trades)

    report = baseline.run(baseline.SOURCE)

    assert report["promotion_gates"]["full_base_drawdown"] is False
    assert report["shadow_candidate"] is False
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False


def test_fixed_stop_report_cannot_override_failed_drawdown(monkeypatch) -> None:
    dates = pd.to_datetime(
        ["2024-01-02"] * 100 + ["2025-01-02"] * 100 + ["2026-01-02"] * 75
    )
    pnl = [10.0, -110.0] * 137 + [10.0]
    trades = pd.DataFrame(
        {
            "exit_date": dates,
            "base_pnl": pnl,
            "stress_1_pnl": [value - 2.5 for value in pnl],
            "stress_2_pnl": [value - 5.0 for value in pnl],
            "stopped": [value < 0 for value in pnl],
        }
    )
    monkeypatch.setattr(
        stopped,
        "load_stopped_round_trips",
        lambda _path: (trades, {"scored_rows": len(trades)}),
    )

    report = stopped.run(stopped.SOURCE)

    assert report["promotion_gates"]["full_base_drawdown"] is False
    assert report["shadow_candidate"] is False
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False


def test_weekday_proxy_uses_next_cash_open_and_frozen_exit_days() -> None:
    index = pd.DatetimeIndex(
        [
            "2026-08-02 18:00:00-04:00",
            "2026-08-03 09:30:00-04:00",
            "2026-08-03 18:00:00-04:00",
            "2026-08-04 09:30:00-04:00",
            "2026-08-04 18:00:00-04:00",
            "2026-08-05 09:30:00-04:00",
        ]
    )
    frame = pd.DataFrame(
        {
            "Open": [100.0, 102.0, 102.0, 101.0, 101.0, 104.0],
            "Close": [100.0, 102.0, 102.0, 101.0, 101.0, 104.0],
        },
        index=index,
    )

    trades = weekday.build_trades(frame)

    assert list(trades["exit_weekday"]) == ["Monday", "Tuesday", "Wednesday"]
    assert list(trades["eligible"]) == [True, False, True]
    assert round(float(trades.iloc[0]["pnl"]), 2) == 3.78


def test_bbo_holdout_keeps_degraded_sensitive_pass_out_of_practice(
    monkeypatch, tmp_path
) -> None:
    dates = pd.date_range("2026-07-20", periods=11, freq="D", tz="America/New_York")
    base_pnl = [500.0, 50.0] + [-40.0] * 9
    trades = pd.DataFrame(
        {
            "exit_timestamp": dates,
            "eligible": [True] * 11,
            "base_pnl": base_pnl,
            "stress_1_pnl": [value - 2.5 for value in base_pnl],
            "stress_2_pnl": [value - 5.0 for value in base_pnl],
        }
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        '{"dataset_conditions":[{"date":"2026-07-20","condition":"degraded"}]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(bbo, "MANIFEST", manifest)
    monkeypatch.setattr(
        bbo,
        "load_trades",
        lambda _path: (trades, {"paired_sessions": len(trades)}),
    )

    report = bbo.run(bbo.SOURCE)

    assert report["bbo_holdout_supportive"] is True
    assert report["data_quality_sensitivity"]["clean_data_supportive"] is False
    assert report["forward_shadow_candidate"] is True
    assert report["practice_promotion_eligible"] is False
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
