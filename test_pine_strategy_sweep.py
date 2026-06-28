from pathlib import Path

import pandas as pd

from research.pine_strategy_lab import BacktestMetrics
from research.pine_strategy_sweep import estimate_pbo_score, parse_date_ranges, run_strategy_sweep, write_sweep_report


def test_parse_date_ranges_accepts_colon_pairs():
    assert parse_date_ranges(["2020-01-01:2021-01-01", "2022-01-01:2024-12-31"]) == [
        ("2020-01-01", "2021-01-01"),
        ("2022-01-01", "2024-12-31"),
    ]


def test_strategy_sweep_runs_symbols_ranges_and_parameter_grid(tmp_path: Path):
    strategy_file = tmp_path / "toy_strategy.py"
    strategy_file.write_text(
        """
import pandas as pd

PARAM_GRID = [{"lookback": 10}, {"lookback": 20}]

def strategy(ohlcv: pd.DataFrame, lookback: int = 10) -> pd.Series:
    return pd.Series(0, index=ohlcv.index)
""",
        encoding="utf-8",
    )

    seen = []

    def fake_backtest(strategy_fn, config):
        seen.append((config.symbol, config.start, config.end, strategy_fn._sweep_params))
        boost = 0.3 if strategy_fn._sweep_params["lookback"] == 20 else 0.0
        symbol_boost = 0.2 if config.symbol == "QQQ" else 0.0
        return BacktestMetrics(
            total_return_pct=20.0 + boost,
            profit_factor=1.4 + boost + symbol_boost,
            max_drawdown_pct=8.0,
            trade_count=80,
            out_of_sample_profit_factor=1.2 + boost,
            walk_forward_pass_rate=0.65,
            sharpe_ratio=1.5 + boost,
            win_rate_pct=55.0,
        )

    results = run_strategy_sweep(
        strategy_file,
        symbols=["SPY", "QQQ"],
        date_ranges=[("2022-01-01", "2024-12-31")],
        backtest_fn=fake_backtest,
    )

    assert len(results) == 4
    assert len(seen) == 4
    assert results[0].symbol == "QQQ"
    assert results[0].params == {"lookback": 20}
    assert results[0].evaluation.status == "paper_candidate"


def test_write_sweep_report_sorts_and_includes_params(tmp_path: Path):
    strategy_file = tmp_path / "toy_strategy.py"
    strategy_file.write_text(
        """
import pandas as pd

PARAM_GRID = [{"lookback": 5}]

def strategy(ohlcv: pd.DataFrame, lookback: int = 5) -> pd.Series:
    return pd.Series(0, index=ohlcv.index)
""",
        encoding="utf-8",
    )

    def fake_backtest(strategy_fn, config):
        return BacktestMetrics(25.0, 1.6, 7.0, 90, 1.25, 0.7, sharpe_ratio=1.2, win_rate_pct=58.0)

    results = run_strategy_sweep(
        strategy_file,
        symbols=["SPY"],
        date_ranges=[("2022-01-01", "2024-12-31")],
        backtest_fn=fake_backtest,
    )
    out = tmp_path / "sweep.md"
    write_sweep_report(results, out)

    text = out.read_text(encoding="utf-8")
    assert "Pine Strategy Sweep Report" in text
    assert "PBO score:" in text
    assert "lookback=5" in text
    assert "SPY" in text


def test_strategy_sweep_fetches_each_symbol_window_once(tmp_path: Path):
    strategy_file = tmp_path / "toy_strategy.py"
    strategy_file.write_text(
        """
import pandas as pd

PARAM_GRID = [{"lookback": 5}, {"lookback": 10}]

def strategy(ohlcv: pd.DataFrame, lookback: int = 5) -> pd.Series:
    return pd.Series(1, index=ohlcv.index)
""",
        encoding="utf-8",
    )
    calls = []

    def fake_fetch(symbol: str, start: str, end: str):
        calls.append((symbol, start, end))
        idx = pd.date_range(start, periods=40, freq="D")
        return pd.DataFrame(
            {
                "open": range(100, 140),
                "high": range(101, 141),
                "low": range(99, 139),
                "close": range(100, 140),
                "volume": [1_000] * 40,
            },
            index=idx,
        )

    results = run_strategy_sweep(
        strategy_file,
        symbols=["SPY"],
        date_ranges=[("2022-01-01", "2022-03-01")],
        fetch_fn=fake_fetch,
    )

    assert len(results) == 2
    assert calls == [("SPY", "2022-01-01", "2022-03-01")]


def test_estimate_pbo_score_flags_is_winners_that_fail_oos():
    rows = [
        BacktestMetrics(20.0, 4.0, 8.0, 80, 0.7, 0.2),
        BacktestMetrics(18.0, 3.5, 8.0, 80, 0.8, 0.2),
        BacktestMetrics(12.0, 1.4, 8.0, 80, 1.5, 0.8),
        BacktestMetrics(10.0, 1.3, 8.0, 80, 1.4, 0.8),
    ]

    assert estimate_pbo_score(rows) == 1.0


def test_estimate_pbo_score_stays_low_when_is_winners_hold_oos_rank():
    rows = [
        BacktestMetrics(20.0, 3.0, 8.0, 80, 2.8, 0.8),
        BacktestMetrics(18.0, 2.7, 8.0, 80, 2.5, 0.8),
        BacktestMetrics(12.0, 1.4, 8.0, 80, 1.2, 0.6),
        BacktestMetrics(10.0, 1.3, 8.0, 80, 1.1, 0.6),
    ]

    assert estimate_pbo_score(rows) == 0.0


def test_strategy_sweep_attaches_population_pbo_score_to_metrics(tmp_path: Path):
    strategy_file = tmp_path / "toy_strategy.py"
    strategy_file.write_text(
        """
import pandas as pd

PARAM_GRID = [{"rank": 1}, {"rank": 2}, {"rank": 3}, {"rank": 4}]

def strategy(ohlcv: pd.DataFrame, rank: int = 1) -> pd.Series:
    return pd.Series(0, index=ohlcv.index)
""",
        encoding="utf-8",
    )

    def fake_backtest(strategy_fn, config):
        rank = strategy_fn._sweep_params["rank"]
        return BacktestMetrics(
            total_return_pct=20.0,
            profit_factor=5 - rank,
            max_drawdown_pct=8.0,
            trade_count=80,
            out_of_sample_profit_factor=rank,
            walk_forward_pass_rate=0.8,
        )

    results = run_strategy_sweep(
        strategy_file,
        symbols=["SPY"],
        date_ranges=[("2022-01-01", "2024-12-31")],
        backtest_fn=fake_backtest,
    )

    assert {result.metrics.pbo_score for result in results} == {1.0}
    assert all(result.evaluation.status == "rejected" for result in results)
