from __future__ import annotations

from pathlib import Path

from research import causal_trade_replay_lab as replay
from research import options_exit_policy_lab as exit_lab


def _life(day: int, bids: tuple[float, ...] = (1.0, 0.8)) -> exit_lab.Lifecycle:
    return exit_lab.Lifecycle(
        lifecycle_id=f"life-{day}",
        date=f"2026-01-{day:02d}",
        symbol="SPY",
        right="CALL",
        strategy="0dte",
        day_type="trend",
        entry_premium=1.0,
        marks=tuple(
            exit_lab.Mark(
                ts=f"2026-01-{day:02d}T09:{30 + index:02d}:00",
                bid=bid,
                mark=bid,
                ret_pct=(bid - 1.0) * 100,
                best_pct=None,
                reason="hard_close" if index == len(bids) - 1 else "mark",
                ask=bid + 0.02,
            )
            for index, bid in enumerate(bids)
        ),
        entry_at=f"2026-01-{day:02d}T09:30:00",
    )


def test_autopsy_separates_bad_entry_from_salvageable_exit() -> None:
    policies = {
        "baseline_current": lambda life: (-20.0, "late_exit"),
        "early_exit": lambda life: (10.0, "early_exit"),
    }
    salvageable = replay.autopsy_lifecycle(
        _life(1, (1.0, 1.2, 0.8)), policies=policies, fee_pct=0.0
    )
    bad_entry = replay.autopsy_lifecycle(
        _life(2, (1.0, 0.9, 0.8)), policies=policies, fee_pct=0.0
    )

    assert salvageable["diagnosis"] == "exit_policy_salvageable_hindsight_only"
    assert salvageable["oracle_best_policy"] == "early_exit"
    assert salvageable["oracle_hindsight_only"] is True
    assert bad_entry["diagnosis"] == "entry_never_profitable_after_cost"


def test_walk_forward_never_selects_policy_from_future_winner() -> None:
    lives = [_life(day) for day in range(1, 7)]

    def prior_winner(life: exit_lab.Lifecycle) -> exit_lab.PolicyResult:
        return (10.0 if life.date < "2026-01-06" else -10.0, "a")

    def future_winner(life: exit_lab.Lifecycle) -> exit_lab.PolicyResult:
        return (-5.0 if life.date < "2026-01-06" else 100.0, "b")

    policies = {
        "baseline_current": lambda life: (-20.0, "baseline"),
        "prior_winner": prior_winner,
        "future_winner": future_winner,
    }
    result = replay.walk_forward_replay(
        lives,
        policies=policies,
        fee_pct=0.0,
        min_train_dates=5,
        min_context_samples=1,
        min_context_dates=1,
    )

    assert result["oos_trades"] == 1
    assert result["outcomes"][0]["selected_policy"] == "prior_winner"
    assert result["outcomes"][0]["selected_return_pct"] == -10.0
    assert result["outcomes"][0]["baseline_loss_salvaged"] is False


def test_walk_forward_counts_real_oos_salvage_and_spoiled_winners() -> None:
    lives = [_life(day) for day in range(1, 8)]
    policies = {
        "baseline_current": lambda life: (-10.0 if life.date.endswith("06") else 5.0, "baseline"),
        "defensive": lambda life: (8.0, "defensive"),
    }
    result = replay.walk_forward_replay(
        lives,
        policies=policies,
        fee_pct=0.0,
        min_train_dates=5,
        min_context_samples=1,
        min_context_dates=1,
    )

    assert result["baseline_losses_salvaged"] == 1
    assert result["baseline_winners_spoiled"] == 0
    assert result["selected_policy_counts"] == {"defensive": 2}


def test_selector_falls_back_to_baseline_when_every_challenger_is_fragile() -> None:
    history = [_life(day) for day in range(1, 6)]
    policies = {
        "baseline_current": lambda life: (-2.0, "baseline"),
        "less_bad_but_still_negative": lambda life: (-1.0, "challenger"),
    }

    selection = replay.select_policy_from_history(
        history,
        _life(6),
        policies=policies,
        fee_pct=0.0,
        min_context_samples=1,
        min_context_dates=1,
    )

    assert selection["policy"] == "baseline_current"
    assert selection["selection_reason"] == "fallback_baseline_no_positive_robust_prior_edge"


def test_delayed_entry_uses_recorded_ask_and_can_skip_without_trigger() -> None:
    life = _life(1, (1.0, 0.80, 1.00, 1.20))
    rebased, reason = replay._dip_recovery_entry(life)

    assert reason == "recovering_after_15pct_dip"
    assert rebased is not None
    assert rebased.entry_premium == 1.02
    assert rebased.entry_at.endswith("09:32:00")

    missing, reason = replay._first_green_confirmation(_life(2, (1.0, 0.9, 0.8)))
    assert missing is None
    assert reason == "never_confirmed_above_original_entry"


def test_entry_timing_report_counts_skipped_signals_as_zero_not_winners() -> None:
    lives = [_life(1, (1.0, 0.9, 0.8)), _life(2, (1.0, 1.2, 1.3))]
    report = replay.evaluate_entry_timing_variants(
        lives,
        fee_pct=0.0,
        exit_policy=lambda life: (10.0, "test_exit"),
    )

    green = report["variants"]["first_green_confirmation"]
    assert green["signals"] == 2
    assert green["trades_triggered"] == 1
    assert green["per_signal_metrics"]["n"] == 2
    assert green["per_signal_metrics"]["gross_pct"] == 10.0


def test_entry_feature_attribution_compares_only_pre_entry_context() -> None:
    losses = []
    wins = []
    for day in range(1, 7):
        losing = _life(day)
        winning = _life(day + 10)
        object.__setattr__(losing, "features", {"above_vwap": False})
        object.__setattr__(winning, "features", {"above_vwap": True})
        losses.append(losing)
        wins.append(winning)

    original = replay.exit_lab.POLICIES["baseline_current"]
    replay.exit_lab.POLICIES["baseline_current"] = (
        lambda life: (-10.0, "loss") if life.features["above_vwap"] is False else (10.0, "win")
    )
    try:
        report = replay.entry_feature_attribution(
            losses + wins, fee_pct=0.0, min_samples=2, min_dates=2
        )
    finally:
        replay.exit_lab.POLICIES["baseline_current"] = original

    by_value = {
        row["value"]: row
        for row in report["ranked_risk_to_opportunity"]
        if row["feature"] == "above_vwap"
    }
    assert by_value["false"]["risk_flag"] is True
    assert by_value["false"]["expectancy_delta_vs_complement_pct"] == -20.0


def test_build_report_is_read_only() -> None:
    report = replay.build_report(candidates_path=replay.Path("missing.jsonl"))
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["automatic_parameter_changes"] is False
    assert report["promotion_authority"].startswith("none_")


def test_nightly_execution_challenger_runner_refreshes_causal_replay() -> None:
    root = Path(__file__).resolve().parents[2]
    runner = (root / "scripts" / "run_flip_execution_challenger_report.ps1").read_text(
        encoding="utf-8"
    )

    assert "python research\\causal_trade_replay_lab.py" in runner
