from research.liquidity_sweep_mss_retest_lab import summarize
from strategies.topstep_replay_backtester import TradeResult
from datetime import datetime


def _trade(pnl: float) -> TradeResult:
    now = datetime(2026, 8, 18, 10, 0)
    return TradeResult(
        date="2026-08-18",
        entry_time=now,
        exit_time=now,
        side="buy",
        entry_price=100.0,
        exit_price=101.0,
        contracts=1,
        pnl=pnl,
        win=pnl > 0,
        exit_reason="target" if pnl > 0 else "stop",
    )


def test_summarize_applies_incremental_doubled_friction() -> None:
    baseline = summarize([_trade(20.0), _trade(-10.0)])
    stressed = summarize([_trade(20.0), _trade(-10.0)], extra_friction=4.98)
    assert baseline["expectancy"] == 5.0
    assert stressed["expectancy"] == 0.02
    assert stressed["total_pnl"] == 0.04
