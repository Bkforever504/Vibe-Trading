#!/usr/bin/env python3
"""Walk-forward test for the causal daily stock screener.

Signals use day-t completed OHLCV and enter at day t+1 open. The original
next-session intraday test is preserved, while preregistered 5- and 20-session
tests check whether a medium-term momentum screen was being judged on the
wrong horizon. Longer tests use fixed non-overlapping rebalance dates and must
beat SPY as well as costs. The fixed present-day universe creates survivorship
bias, so a passing result can authorize shadow review only.
"""
from __future__ import annotations

import argparse
import json
import math
import warnings
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "data" / "daily_stock_screener_lab_results.json"
UNIVERSE = (
    "SPY", "QQQ", "IWM", "DIA", "SMH", "XLK", "XLF", "XLV", "XLE", "XLY", "XLP", "XLU",
    "AAPL", "MSFT", "NVDA", "AVGO", "AMD", "META", "AMZN", "GOOGL", "TSLA", "PLTR", "COIN", "NFLX",
)
ROUND_TRIP_COST = 0.0020
HORIZON_FIELDS = {
    1: "next_intraday_return",
    5: "next_5d_return",
    20: "next_20d_return",
}


def fetch_history(symbols: tuple[str, ...] = UNIVERSE, start: str = "2013-01-01") -> dict[str, pd.DataFrame]:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError("yfinance is required for the screener lab") from exc
    frames: dict[str, pd.DataFrame] = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for symbol in symbols:
            frame = yf.download(symbol, start=start, auto_adjust=True, progress=False)
            if frame.empty:
                continue
            frame.columns = [column.lower() if isinstance(column, str) else column[0].lower() for column in frame.columns]
            frames[symbol] = frame[["open", "high", "low", "close", "volume"]].dropna().astype(float)
    return frames


def feature_table(frame: pd.DataFrame, spy_close: pd.Series) -> pd.DataFrame:
    close = frame["close"]
    previous = close.shift(1)
    true_range = pd.concat(
        [frame["high"] - frame["low"], (frame["high"] - previous).abs(), (frame["low"] - previous).abs()],
        axis=1,
    ).max(axis=1)
    out = pd.DataFrame(index=frame.index)
    out["price"] = close
    out["sma20"] = close.rolling(20).mean()
    out["sma50"] = close.rolling(50).mean()
    out["sma200"] = close.rolling(200).mean()
    out["adv20"] = (close * frame["volume"]).rolling(20).mean()
    out["atr_pct"] = true_range.rolling(14).mean().div(close).mul(100.0)
    out["return20"] = close.pct_change(20).mul(100.0)
    out["return63"] = close.pct_change(63).mul(100.0)
    aligned_spy = spy_close.reindex(frame.index).ffill()
    out["relative20"] = out["return20"] - aligned_spy.pct_change(20).mul(100.0)
    out["relative63"] = out["return63"] - aligned_spy.pct_change(63).mul(100.0)
    out["distance20"] = close.div(out["sma20"]).sub(1.0).mul(100.0)
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    out["rsi14"] = 100.0 - 100.0 / (1.0 + gain.div(loss.replace(0, float("nan"))))
    out["long_trend"] = (close > out["sma20"]) & (out["sma20"] > out["sma50"]) & (out["sma50"] > out["sma200"])
    out["short_trend"] = (close < out["sma20"]) & (out["sma20"] < out["sma50"]) & (out["sma50"] < out["sma200"])
    out["liquid"] = (close >= 10.0) & (out["adv20"] >= 250_000_000.0) & out["atr_pct"].between(0.75, 7.0)
    out["long_full"] = out["liquid"] & out["long_trend"] & (out["relative20"] > 0) & (out["return63"] > 0) & (out["distance20"] <= 8.0) & (out["rsi14"] <= 75.0)
    out["short_full"] = out["liquid"] & out["short_trend"] & (out["relative20"] < 0) & (out["return63"] < 0) & (out["distance20"] >= -8.0) & (out["rsi14"] >= 25.0)
    out["rank_long"] = out["relative20"].clip(lower=0) * 3.0 + out["relative63"].clip(lower=0) + out["return20"].clip(lower=0)
    out["rank_short"] = (-out["relative20"]).clip(lower=0) * 3.0 + (-out["relative63"]).clip(lower=0) + (-out["return20"]).clip(lower=0)
    out["next_intraday_return"] = frame["close"].shift(-1).div(frame["open"].shift(-1)).sub(1.0)
    out["next_5d_return"] = frame["close"].shift(-5).div(frame["open"].shift(-1)).sub(1.0)
    out["next_20d_return"] = frame["close"].shift(-20).div(frame["open"].shift(-1)).sub(1.0)
    return out


def _posture_table(features: dict[str, pd.DataFrame]) -> pd.Series:
    spy = features["SPY"]
    dates = spy.index
    above50 = pd.concat(
        {symbol: table["price"] > table["sma50"] for symbol, table in features.items()}, axis=1
    ).reindex(dates).mean(axis=1)
    above200 = pd.concat(
        {symbol: table["price"] > table["sma200"] for symbol, table in features.items()}, axis=1
    ).reindex(dates).mean(axis=1)
    risk_on = spy["long_trend"].reindex(dates).fillna(False) & (above50 >= 0.60) & (above200 >= 0.55)
    risk_off = spy["short_trend"].reindex(dates).fillna(False) | (above50 < 0.40) | (above200 < 0.40)
    posture = pd.Series("mixed", index=dates)
    posture.loc[risk_on] = "risk_on"
    posture.loc[risk_off] = "risk_off"
    return posture


def build_trades(
    frames: dict[str, pd.DataFrame],
    variant: str,
    cost: float,
    *,
    holding_days: int = 1,
    long_only: bool = False,
    non_overlapping: bool = False,
) -> pd.DataFrame:
    if holding_days not in HORIZON_FIELDS:
        raise ValueError(f"Unsupported holding_days={holding_days}")
    spy_close = frames["SPY"]["close"]
    features = {symbol: feature_table(frame, spy_close) for symbol, frame in frames.items()}
    posture = _posture_table(features)
    return_field = HORIZON_FIELDS[holding_days]
    eligible_dates = set(posture.index)
    if non_overlapping:
        # Fixed phase zero, anchored after the 200-session feature warm-up.
        eligible_dates = set(posture.index[200::holding_days])
    rows: list[dict[str, Any]] = []
    for day in posture.index:
        if day not in eligible_dates:
            continue
        spy_row = features["SPY"].loc[day]
        if pd.isna(spy_row.get(return_field)):
            continue
        spy_gross = float(spy_row[return_field])
        candidates: list[dict[str, Any]] = []
        for symbol, table in features.items():
            if symbol == "SPY" or day not in table.index:
                continue
            row = table.loc[day]
            if pd.isna(row.get(return_field)):
                continue
            if variant == "liquidity_only":
                long_ok, short_ok = bool(row["liquid"]), False
            elif variant == "trend_only":
                long_ok, short_ok = bool(row["liquid"] and row["long_trend"]), bool(row["liquid"] and row["short_trend"])
            else:
                long_ok, short_ok = bool(row["long_full"]), bool(row["short_full"])
            if variant == "full_screen_market_posture":
                long_ok = long_ok and posture.loc[day] != "risk_off"
                short_ok = short_ok and posture.loc[day] != "risk_on"
            if long_only:
                short_ok = False
            if long_ok:
                candidates.append({
                    "symbol": symbol,
                    "direction": "long",
                    "rank": float(row["rank_long"]),
                    "gross": float(row[return_field]),
                    "benchmark_gross": spy_gross,
                })
            if short_ok:
                candidates.append({
                    "symbol": symbol,
                    "direction": "short",
                    "rank": float(row["rank_short"]),
                    "gross": -float(row[return_field]),
                    "benchmark_gross": -spy_gross,
                })
        candidates.sort(key=lambda item: item["rank"], reverse=True)
        for candidate in candidates[:3]:
            rows.append({
                "signal_date": day,
                "symbol": candidate["symbol"],
                "direction": candidate["direction"],
                "market_posture": posture.loc[day],
                "holding_days": holding_days,
                "gross_return": candidate["gross"],
                "net_return": candidate["gross"] - cost,
                "spy_direction_matched_return": candidate["benchmark_gross"],
                "spy_relative_excess_return": candidate["gross"] - candidate["benchmark_gross"],
            })
    return pd.DataFrame(rows)


def metrics(trades: pd.DataFrame) -> dict[str, Any]:
    if trades.empty:
        return {"trade_count": 0}
    net = trades["net_return"].astype(float)
    daily = trades.groupby("signal_date")["net_return"].mean().sort_index()
    equity = (1.0 + daily).cumprod()
    drawdown = equity.div(equity.cummax()).sub(1.0)
    gains = float(net[net > 0].sum())
    losses = abs(float(net[net < 0].sum()))
    sharpe = float(daily.mean() / daily.std() * math.sqrt(252.0)) if daily.std() else 0.0
    return {
        "trade_count": int(len(trades)),
        "trading_date_count": int(trades["signal_date"].nunique()),
        "mean_net_return_pct": round(float(net.mean()) * 100.0, 4),
        "mean_spy_relative_excess_pct": round(
            float(trades["spy_relative_excess_return"].mean()) * 100.0, 4
        ) if "spy_relative_excess_return" in trades else None,
        "win_rate": round(float((net > 0).mean()), 4),
        "profit_factor": round(gains / losses, 3) if losses else None,
        "daily_sharpe": round(sharpe, 3),
        "max_drawdown_pct": round(abs(float(drawdown.min())) * 100.0, 3),
    }


def _split(trades: pd.DataFrame, start: str, end: str | None) -> pd.DataFrame:
    if trades.empty:
        return trades.copy()
    dates = pd.to_datetime(trades["signal_date"])
    mask = dates >= pd.Timestamp(start)
    if end:
        mask &= dates <= pd.Timestamp(end)
    return trades.loc[mask].copy()


def run_lab(frames: dict[str, pd.DataFrame] | None = None) -> dict[str, Any]:
    frames = fetch_history() if frames is None else frames
    experiments = (
        {"id": "liquidity_only_1d_intraday", "variant": "liquidity_only", "holding_days": 1, "long_only": False, "non_overlapping": False},
        {"id": "trend_only_1d_intraday", "variant": "trend_only", "holding_days": 1, "long_only": False, "non_overlapping": False},
        {"id": "full_screen_1d_intraday", "variant": "full_screen", "holding_days": 1, "long_only": False, "non_overlapping": False},
        {"id": "full_screen_market_posture_1d_intraday", "variant": "full_screen_market_posture", "holding_days": 1, "long_only": False, "non_overlapping": False},
        {"id": "full_screen_long_only_5d_nonoverlap", "variant": "full_screen", "holding_days": 5, "long_only": True, "non_overlapping": True},
        {"id": "full_screen_market_posture_long_only_5d_nonoverlap", "variant": "full_screen_market_posture", "holding_days": 5, "long_only": True, "non_overlapping": True},
        {"id": "full_screen_long_only_20d_nonoverlap", "variant": "full_screen", "holding_days": 20, "long_only": True, "non_overlapping": True},
        {"id": "full_screen_market_posture_long_only_20d_nonoverlap", "variant": "full_screen_market_posture", "holding_days": 20, "long_only": True, "non_overlapping": True},
    )
    reports: list[dict[str, Any]] = []
    for experiment in experiments:
        build_args = {
            "holding_days": experiment["holding_days"],
            "long_only": experiment["long_only"],
            "non_overlapping": experiment["non_overlapping"],
        }
        trades = build_trades(frames, experiment["variant"], ROUND_TRIP_COST, **build_args)
        stressed = build_trades(frames, experiment["variant"], ROUND_TRIP_COST * 2.0, **build_args)
        splits = {
            "development_2015_2021": metrics(_split(trades, "2015-01-01", "2021-12-31")),
            "selection_2022_2024": metrics(_split(trades, "2022-01-01", "2024-12-31")),
            "final_2025_plus": metrics(_split(trades, "2025-01-01", None)),
        }
        final_stress = metrics(_split(stressed, "2025-01-01", None))
        passed = bool(
            splits["selection_2022_2024"].get("mean_net_return_pct", -1) > 0
            and splits["selection_2022_2024"].get("mean_spy_relative_excess_pct", -1) > 0
            and splits["final_2025_plus"].get("mean_net_return_pct", -1) > 0
            and splits["final_2025_plus"].get("mean_spy_relative_excess_pct", -1) > 0
            and splits["final_2025_plus"].get("profit_factor", 0) > 1.05
            and final_stress.get("mean_net_return_pct", -1) > 0
            and splits["final_2025_plus"].get("trade_count", 0) >= 100
        )
        reports.append({
            "experiment_id": experiment["id"],
            "variant": experiment["variant"],
            "holding_days": experiment["holding_days"],
            "long_only": experiment["long_only"],
            "non_overlapping": experiment["non_overlapping"],
            "splits": splits,
            "double_cost_final": final_stress,
            "passed_shadow_review_gate": passed,
            "promotion_authority": "shadow_review_only" if passed else "blocked",
            "failed_result_action": None if passed else "do_not_trade_or_invert_post_hoc",
        })
    return {
        "schema_version": 2,
        "experiment": "DAILY-STOCK-SCREENER-CAUSAL-WALK-FORWARD",
        "signal_cutoff": "completed_day_t",
        "execution": "day_t_plus_1_open_to_fixed_1d_5d_or_20d_close",
        "medium_term_rebalance": "fixed_phase_zero_non_overlapping_after_200_session_warmup",
        "promotion_gate": "positive_selection_and_final_net_and_spy_excess_plus_positive_double_cost_final",
        "round_trip_cost": ROUND_TRIP_COST,
        "static_universe_survivorship_bias": True,
        "execution_enabled": False,
        "can_submit_orders": False,
        "results": reports,
        "survivor_count": sum(int(row["passed_shadow_review_gate"]) for row in reports),
        "portfolio_action": "allow_shadow_review_only_for_survivors_otherwise_exclude_from_direction_and_priority",
        "warning": "A survivor is eligible for forward shadow observation only; the static present-day universe prevents production promotion.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = run_lab()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
