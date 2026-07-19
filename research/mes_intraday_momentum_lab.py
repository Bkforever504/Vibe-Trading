#!/usr/bin/env python3
"""Test opening-to-closing-period momentum on deep hourly ES data.

Academic motivation: Gao, Han, Li, and Zhou (2018) document that the first
half-hour market return predicts the final half-hour return. Hourly Yahoo bars
only permit an approximation, so this remains a research candidate.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.topstep_prop_bot import load_candles_csv


MES_POINT_VALUE = 5.0
MES_TICK_VALUE = 1.25


@dataclass(frozen=True)
class MomentumConfig:
    direction: str
    opening_threshold_pct: float
    volume_ratio: float
    require_daily_trend: bool


def _daily_rows(candles: list) -> list[dict]:
    grouped: dict[str, list] = {}
    for candle in candles:
        grouped.setdefault(candle.timestamp.date().isoformat(), []).append(candle)
    rows: list[dict] = []
    prior_close: float | None = None
    closes: list[float] = []
    opening_volumes: list[float] = []
    for date in sorted(grouped):
        bars = sorted(grouped[date], key=lambda bar: bar.timestamp)
        if len(bars) < 5:
            prior_close = bars[-1].close if bars else prior_close
            continue
        first, last = bars[0], bars[-1]
        if prior_close and prior_close > 0:
            rows.append({
                "date": date,
                "opening_return": first.close / prior_close - 1,
                "entry": last.open,
                "exit": last.close,
                "opening_volume": first.volume,
                "volume_average": sum(opening_volumes[-20:]) / min(len(opening_volumes), 20) if opening_volumes else 0,
                "daily_sma20": sum(closes[-20:]) / min(len(closes), 20) if closes else prior_close,
                "prior_close": prior_close,
            })
        prior_close = last.close
        closes.append(last.close)
        opening_volumes.append(first.volume)
    return rows


def simulate(rows: list[dict], config: MomentumConfig, *, doubled_costs: bool = False) -> dict:
    commission = 8.0 if doubled_costs else 4.0
    slippage_cost = MES_TICK_VALUE * (4 if doubled_costs else 2)
    pnls: list[float] = []
    for row in rows:
        opening_return = row["opening_return"]
        if abs(opening_return) < config.opening_threshold_pct:
            continue
        if config.volume_ratio > 0:
            average = row["volume_average"]
            if average <= 0 or row["opening_volume"] < average * config.volume_ratio:
                continue
        side = 1 if opening_return > 0 else -1
        if config.direction == "reversal":
            side *= -1
        if config.require_daily_trend:
            trend_side = 1 if row["prior_close"] >= row["daily_sma20"] else -1
            if side != trend_side:
                continue
        pnl = (row["exit"] - row["entry"]) * MES_POINT_VALUE * side - commission - slippage_cost
        pnls.append(round(pnl, 2))
    gross_profit = sum(value for value in pnls if value > 0)
    gross_loss = -sum(value for value in pnls if value < 0)
    equity = peak = max_drawdown = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return {
        "trades": len(pnls),
        "total_pnl": round(sum(pnls), 2),
        "daily_average": round(sum(pnls) / len(rows), 4) if rows else 0,
        "expectancy": round(sum(pnls) / len(pnls), 4) if pnls else 0,
        "win_rate": round(sum(value > 0 for value in pnls) / len(pnls), 4) if pnls else 0,
        "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else ("inf" if gross_profit else 0),
        "max_drawdown": round(max_drawdown, 2),
        "pnls": pnls,
    }


def run_lab(csv_path: Path) -> dict:
    rows = _daily_rows(load_candles_csv(csv_path))
    holdout_at = int(len(rows) * 0.80)
    dev, holdout = rows[:holdout_at], rows[holdout_at:]
    third = len(dev) // 3
    windows = (dev[:third], dev[third:third * 2], dev[third * 2:])
    ranked: list[tuple[float, MomentumConfig, list[dict]]] = []
    for direction in ("momentum", "reversal"):
        for threshold in (0.0, 0.0005, 0.001, 0.002, 0.003, 0.005):
            for volume_ratio in (0.0, 1.0, 1.2, 1.5):
                for trend in (False, True):
                    config = MomentumConfig(direction, threshold, volume_ratio, trend)
                    metrics = [simulate(window, config) for window in windows]
                    if any(row["trades"] < 15 or row["expectancy"] <= 0 or row["profit_factor"] == "inf" or row["profit_factor"] < 1.05 for row in metrics):
                        continue
                    score = min(row["expectancy"] for row in metrics) - max(row["max_drawdown"] for row in metrics) * 0.01
                    ranked.append((score, config, metrics))
    ranked.sort(key=lambda item: item[0], reverse=True)
    finalists = []
    for score, config, regimes in ranked[:20]:
        base = simulate(holdout, config)
        stress = simulate(holdout, config, doubled_costs=True)
        finalists.append({
            "config": asdict(config), "development_score": round(score, 4),
            "development_regimes": [{k: v for k, v in row.items() if k != "pnls"} for row in regimes],
            "holdout": {k: v for k, v in base.items() if k != "pnls"},
            "holdout_double_costs": {k: v for k, v in stress.items() if k != "pnls"},
        })
    robust = [row for row in finalists if row["holdout"]["trades"] >= 20 and row["holdout"]["expectancy"] > 0 and row["holdout_double_costs"]["expectancy"] > 0]
    robust.sort(key=lambda row: row["holdout_double_costs"]["expectancy"], reverse=True)
    return {
        "dataset": str(csv_path), "daily_rows": len(rows), "development_rows": len(dev),
        "locked_holdout_rows": len(holdout), "development_survivors": len(ranked),
        "robust_finalists": robust, "all_finalists": finalists,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="MES intraday momentum lab")
    parser.add_argument("--csv", type=Path, default=ROOT / "examples" / "es_1h_730d_fresh.csv")
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "mes_intraday_momentum_results.json")
    args = parser.parse_args()
    report = run_lab(args.csv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in {"robust_finalists", "all_finalists"}}, indent=2))
    for row in report["robust_finalists"]:
        print(json.dumps(row))


if __name__ == "__main__":
    main()
