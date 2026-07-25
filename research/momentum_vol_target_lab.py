"""Diagnostic volatility-target overlay for the frozen ETF momentum lane.

This is research-only. Historical periods have already been consumed by other
project work, so results cannot promote or modify the live/paper strategy.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.momentum_rotation_backtest import (
    _momentum_signal,
    _normalize_position,
    fetch_universe,
)

REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "momentum-vol-target-lab.json"
SYMBOLS = ["SPY", "QQQ", "GLD", "XLE", "TLT", "IWM", "XLK", "XLV", "XLF", "XLI"]


@dataclass(frozen=True)
class VolTargetConfig:
    target_vol: float
    vol_lookback: int
    max_exposure: float = 1.0
    smoothing_span: int = 10
    cost_bps: float = 2.0


def lagged_vol_exposure(
    returns: pd.Series,
    config: VolTargetConfig,
) -> pd.Series:
    """Size from information available before the return being traded."""
    realized = (
        returns.rolling(config.vol_lookback, min_periods=config.vol_lookback)
        .std(ddof=1)
        .mul(np.sqrt(252.0))
        .shift(1)
    )
    raw = (config.target_vol / realized.replace(0.0, np.nan)).clip(
        lower=0.0,
        upper=config.max_exposure,
    )
    return raw.ewm(span=config.smoothing_span, adjust=False).mean().fillna(0.0)


def momentum_returns(closes: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    signal = _momentum_signal(closes, 12 * 21, rebalance_days=5, top_n=2)
    positions = signal.shift(1).map(_normalize_position)
    asset_returns = closes.pct_change().fillna(0.0)
    result = pd.Series(0.0, index=closes.index)
    switches = pd.Series(0.0, index=closes.index)
    previous = None
    for timestamp, position in positions.items():
        if position:
            result.loc[timestamp] = sum(
                float(asset_returns.loc[timestamp, symbol]) / len(position)
                for symbol in position
            )
        if position != previous:
            switches.loc[timestamp] = 1.0
        previous = position
    return result, switches


def net_returns(
    gross: pd.Series,
    switches: pd.Series,
    exposure: pd.Series,
    cost_bps: float,
) -> pd.Series:
    exposure_turnover = exposure.diff().abs().fillna(exposure)
    position_turnover = switches * exposure
    costs = (exposure_turnover + position_turnover) * cost_bps / 10_000.0
    return gross * exposure - costs


def metrics(returns: pd.Series) -> dict[str, float | int]:
    clean = returns.dropna()
    if clean.empty:
        return {"days": 0}
    equity = (1.0 + clean).cumprod()
    drawdown = equity / equity.cummax() - 1.0
    volatility = float(clean.std(ddof=1) * np.sqrt(252.0)) if len(clean) > 1 else 0.0
    sharpe = (
        float(clean.mean() / clean.std(ddof=1) * np.sqrt(252.0))
        if len(clean) > 1 and clean.std(ddof=1) > 0
        else 0.0
    )
    return {
        "days": int(len(clean)),
        "total_return_pct": round(float((equity.iloc[-1] - 1.0) * 100.0), 3),
        "annualized_vol_pct": round(volatility * 100.0, 3),
        "sharpe": round(sharpe, 3),
        "max_drawdown_pct": round(float(abs(drawdown.min()) * 100.0), 3),
    }


def regime_metrics(returns: pd.Series) -> dict[str, dict[str, float | int]]:
    return {
        "development_through_2020": metrics(returns.loc[:"2020-12-31"]),
        "selection_2021_2023": metrics(returns.loc["2021-01-01":"2023-12-31"]),
        "diagnostic_2024_plus": metrics(returns.loc["2024-01-01":]),
    }


def run_lab(closes: pd.DataFrame) -> dict:
    gross, switches = momentum_returns(closes)
    baseline_exposure = pd.Series(1.0, index=gross.index)
    baseline = net_returns(gross, switches, baseline_exposure, cost_bps=2.0)
    candidates = []
    for lookback in (20, 60):
        for target in (0.08, 0.10, 0.12, 0.15):
            config = VolTargetConfig(target_vol=target, vol_lookback=lookback)
            exposure = lagged_vol_exposure(gross, config)
            base_cost = net_returns(gross, switches, exposure, config.cost_bps)
            double_cost = net_returns(gross, switches, exposure, config.cost_bps * 2.0)
            candidates.append({
                "config": asdict(config),
                "average_exposure": round(float(exposure.mean()), 4),
                "base_cost": regime_metrics(base_cost),
                "double_cost": regime_metrics(double_cost),
            })
    return {
        "status": "diagnostic_only_consumed_history",
        "execution_enabled": False,
        "baseline": regime_metrics(baseline),
        "candidates": candidates,
        "notes": [
            "Exposure uses lagged realized volatility and is capped at 100%; no leverage.",
            "Costs include position switches and changes in target exposure.",
            "All periods are already consumed and cannot authorize promotion.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument("--end", default="2026-07-25")
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    closes = fetch_universe(SYMBOLS, args.start, args.end)
    report = run_lab(closes)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
