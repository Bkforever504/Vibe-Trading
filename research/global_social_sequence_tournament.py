#!/usr/bin/env python3
"""Development-only tournament of public social trading sequences.

The module has no broker imports and cannot submit or promote orders. Public
rules are hypotheses; see the frozen source ledger and specification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import NormalDist
from typing import Any, Callable

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SPEC = "research/GLOBAL_SOCIAL_SEQUENCE_TOURNAMENT_SPEC_2026-08-19.md"
SOURCE_LEDGER = ROOT / "research" / "social_strategy_intake" / "global_social_sequence_sources_2026-08-19.json"
DEFAULT_OUT = ROOT / "data" / "global_social_sequence_tournament_results.json"
DEFAULT_REGISTRY = ROOT / "research" / "edge_trials" / "global_social_sequence_registry_2026-08-19.json"

INTRADAY_PATHS = {
    "SPY": ROOT / "data" / "liquid_edge_lab" / "spy_5m.parquet",
    "QQQ": ROOT / "data" / "liquid_edge_lab" / "qqq_5m.parquet",
    "MES": ROOT / "examples" / "mes_v0_1m_2022-01-01_2026-07-19_rth.csv",
}
DAILY_PATHS = {
    "SPY": ROOT / "data" / "htf_volume_screen_lab" / "spy_2015-01-01_2026-07-21.parquet",
    "QQQ": ROOT / "data" / "htf_volume_screen_lab" / "qqq_2015-01-01_2026-07-21.parquet",
}

INTRADAY_FAMILIES = (
    "opening_range_breakout_retest",
    "prior_day_break_retest",
    "liquidity_sweep_mss_fvg",
    "first_touch_rsi_fade",
    "gap_continuation",
    "ema_8_21_break_retest",
    "opening_drive_vwap_pullback",
    "multi_indicator_reversal",
)
DAILY_FAMILIES = (
    "sma200_long_cash",
    "sma5_20_cross",
    "double7",
    "rsi2_200d",
    "multi_ma_majority",
)
REWARD_RISKS = (1.0, 1.5, 2.0, 3.0)
PRIOR_EFFECTIVE_ATTEMPTS = 803
TRIAL_COUNT = len(INTRADAY_FAMILIES) * len(REWARD_RISKS) * len(INTRADAY_PATHS) + len(DAILY_FAMILIES) * len(DAILY_PATHS)
EFFECTIVE_ATTEMPTS = PRIOR_EFFECTIVE_ATTEMPTS + TRIAL_COUNT
BONFERRONI_ALPHA = 0.05 / EFFECTIVE_ATTEMPTS
ETF_NOTIONAL = 10_000.0
ETF_BASELINE_COST = ETF_NOTIONAL * 0.0004
MES_BASELINE_COST = 4.98
MAX_HOLD_BARS = 12


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_registry() -> dict[str, Any]:
    trials: list[dict[str, Any]] = []
    number = 0
    for market in INTRADAY_PATHS:
        for family in INTRADAY_FAMILIES:
            for reward_risk in REWARD_RISKS:
                number += 1
                trials.append({
                    "trial_id": f"GSS-{number:03d}",
                    "horizon": "intraday_5m",
                    "market": market,
                    "family": family,
                    "reward_risk": reward_risk,
                })
    for market in DAILY_PATHS:
        for family in DAILY_FAMILIES:
            number += 1
            trials.append({
                "trial_id": f"GSS-{number:03d}",
                "horizon": "daily",
                "market": market,
                "family": family,
                "reward_risk": None,
            })
    payload = {
        "experiment": "GLOBAL-SOCIAL-SEQUENCE-2026-08-19",
        "specification": SPEC,
        "source_ledger": str(SOURCE_LEDGER.relative_to(ROOT)).replace("\\", "/"),
        "source_ledger_sha256": _sha256(SOURCE_LEDGER),
        "prior_effective_attempts": PRIOR_EFFECTIVE_ATTEMPTS,
        "trial_count": len(trials),
        "effective_attempts": EFFECTIVE_ATTEMPTS,
        "bonferroni_alpha": BONFERRONI_ALPHA,
        "execution_enabled": False,
        "can_submit_orders": False,
        "trials": trials,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload["registry_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    return payload


def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    relative = gain / loss.replace(0, math.nan)
    return 100.0 - 100.0 / (1.0 + relative)


def _features(frame: pd.DataFrame) -> pd.DataFrame:
    bars = frame.copy()
    prior_close = bars["close"].shift(1)
    true_range = pd.concat([
        bars["high"] - bars["low"],
        (bars["high"] - prior_close).abs(),
        (bars["low"] - prior_close).abs(),
    ], axis=1).max(axis=1)
    bars["atr6"] = true_range.shift(1).rolling(6).mean()
    volume = bars["volume"].clip(lower=0)
    typical = (bars["high"] + bars["low"] + bars["close"]) / 3.0
    bars["vwap"] = (typical * volume).cumsum() / volume.cumsum().replace(0, math.nan)
    bars["ema8"] = bars["close"].ewm(span=8, adjust=False).mean()
    bars["ema10"] = bars["close"].ewm(span=10, adjust=False).mean()
    bars["ema20"] = bars["close"].ewm(span=20, adjust=False).mean()
    bars["ema21"] = bars["close"].ewm(span=21, adjust=False).mean()
    bars["ema50"] = bars["close"].ewm(span=50, adjust=False).mean()
    bars["rsi14"] = _rsi(bars["close"], 14)
    low14 = bars["low"].rolling(14).min()
    high14 = bars["high"].rolling(14).max()
    bars["stoch14"] = 100 * (bars["close"] - low14) / (high14 - low14).replace(0, math.nan)
    mean20 = bars["close"].rolling(20).mean()
    deviation = (bars["close"] - mean20).abs().rolling(20).mean()
    bars["cci20"] = (bars["close"] - mean20) / (0.015 * deviation.replace(0, math.nan))
    bars["momentum10"] = bars["close"] - bars["close"].shift(10)
    macd = bars["close"].ewm(span=12, adjust=False).mean() - bars["close"].ewm(span=26, adjust=False).mean()
    bars["macd"] = macd
    bars["macd_signal"] = macd.ewm(span=9, adjust=False).mean()
    return bars


def load_intraday(path: Path, market: str) -> tuple[list[str], dict[str, pd.DataFrame]]:
    raw = pd.read_csv(path) if path.suffix.lower() == ".csv" else pd.read_parquet(path)
    if isinstance(raw.index, pd.DatetimeIndex):
        raw = raw.reset_index()
    time_column = "timestamp" if "timestamp" in raw.columns else raw.columns[0]
    raw["dt"] = pd.to_datetime(raw[time_column], errors="raise")
    if raw["dt"].dt.tz is not None:
        raw["dt"] = raw["dt"].dt.tz_convert("America/New_York").dt.tz_localize(None)
    raw = raw[(raw["dt"].dt.time >= pd.Timestamp("09:30").time()) & (raw["dt"].dt.time < pd.Timestamp("16:00").time())]
    raw["date"] = raw["dt"].dt.date.astype(str)
    sessions: dict[str, pd.DataFrame] = {}
    for day, minute in raw.groupby("date", sort=True):
        fields: dict[str, str] = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        if "instrument_id" in minute.columns:
            fields["instrument_id"] = "last"
        bars = minute.set_index("dt").resample("5min", label="left", closed="left").agg(fields).dropna().reset_index()
        if len(bars) < 78 or bars.iloc[0]["dt"].time() != pd.Timestamp("09:30").time() or bars.iloc[-1]["dt"].time() < pd.Timestamp("15:55").time():
            continue
        if market == "MES" and "instrument_id" in bars and bars["instrument_id"].astype(str).nunique() != 1:
            continue
        bars["time"] = bars["dt"].dt.strftime("%H:%M")
        sessions[day] = _features(bars.reset_index(drop=True))
    return sorted(sessions), sessions


def _same_contract(current: pd.DataFrame, previous: pd.DataFrame | None) -> bool:
    if previous is None:
        return False
    if "instrument_id" not in current or "instrument_id" not in previous:
        return True
    return str(current.iloc[0]["instrument_id"]) == str(previous.iloc[-1]["instrument_id"])


def _retest(bars: pd.DataFrame, start: int, level: float, side: int, limit: int = 6) -> int | None:
    for idx in range(start, min(len(bars) - 1, start + limit)):
        row = bars.iloc[idx]
        if side > 0 and float(row["low"]) <= level and float(row["close"]) > level:
            return idx
        if side < 0 and float(row["high"]) >= level and float(row["close"]) < level:
            return idx
    return None


def _opening_range(bars: pd.DataFrame, previous: pd.DataFrame | None) -> tuple[int, int, float] | None:
    opening = bars.iloc[:3]
    upper, lower = float(opening["high"].max()), float(opening["low"].min())
    midpoint = (upper + lower) / 2.0
    for idx in range(3, min(len(bars) - 1, 30)):
        close = float(bars.iloc[idx]["close"])
        side = 1 if close > upper else -1 if close < lower else 0
        if side:
            retest = _retest(bars, idx + 1, upper if side > 0 else lower, side)
            if retest is not None:
                return retest, side, midpoint
    return None


def _prior_break(bars: pd.DataFrame, previous: pd.DataFrame | None) -> tuple[int, int, float] | None:
    if not _same_contract(bars, previous):
        return None
    upper, lower = float(previous["high"].max()), float(previous["low"].min())
    for idx in range(12, min(len(bars) - 1, 48)):
        close = float(bars.iloc[idx]["close"])
        side = 1 if close > upper else -1 if close < lower else 0
        if side:
            retest = _retest(bars, idx + 1, upper if side > 0 else lower, side)
            if retest is not None:
                row = bars.iloc[retest]
                stop = float(row["low"]) if side > 0 else float(row["high"])
                return retest, side, stop
    return None


def _sweep_mss_fvg(bars: pd.DataFrame, previous: pd.DataFrame | None) -> tuple[int, int, float] | None:
    if not _same_contract(bars, previous):
        return None
    upper, lower = float(previous["high"].max()), float(previous["low"].min())
    for sweep_idx in range(3, min(len(bars) - 3, 42)):
        sweep = bars.iloc[sweep_idx]
        side = 1 if float(sweep["low"]) < lower and float(sweep["close"]) > lower else -1 if float(sweep["high"]) > upper and float(sweep["close"]) < upper else 0
        if not side:
            continue
        reference = float(bars.iloc[max(0, sweep_idx - 3):sweep_idx]["high"].max()) if side > 0 else float(bars.iloc[max(0, sweep_idx - 3):sweep_idx]["low"].min())
        for idx in range(sweep_idx + 1, min(len(bars) - 1, sweep_idx + 7)):
            row = bars.iloc[idx]
            atr = float(row["atr6"])
            directional = side * (float(row["close"]) - float(row["open"])) > 0
            displaced = math.isfinite(atr) and directional and abs(float(row["close"]) - float(row["open"])) >= 0.5 * atr
            mss = float(row["close"]) > reference if side > 0 else float(row["close"]) < reference
            fvg = float(row["low"]) > float(bars.iloc[idx - 2]["high"]) if side > 0 else float(row["high"]) < float(bars.iloc[idx - 2]["low"])
            if not (displaced and mss and fvg):
                continue
            midpoint = (float(row["low"]) + float(bars.iloc[idx - 2]["high"])) / 2 if side > 0 else (float(row["high"]) + float(bars.iloc[idx - 2]["low"])) / 2
            retest = _retest(bars, idx + 1, midpoint, side)
            if retest is not None:
                stop = float(sweep["low"]) if side > 0 else float(sweep["high"])
                return retest, side, stop
    return None


def _first_touch_rsi(bars: pd.DataFrame, previous: pd.DataFrame | None) -> tuple[int, int, float] | None:
    if not _same_contract(bars, previous):
        return None
    upper, lower = float(previous["high"].max()), float(previous["low"].min())
    for idx in range(14, min(len(bars) - 1, 54)):
        row = bars.iloc[idx]
        rsi = float(row["rsi14"])
        if float(row["high"]) >= upper and float(row["close"]) < upper and rsi >= 70:
            return idx, -1, float(row["high"])
        if float(row["low"]) <= lower and float(row["close"]) > lower and rsi <= 30:
            return idx, 1, float(row["low"])
    return None


def _gap_continuation(bars: pd.DataFrame, previous: pd.DataFrame | None) -> tuple[int, int, float] | None:
    if not _same_contract(bars, previous):
        return None
    upper, lower = float(previous["high"].max()), float(previous["low"].min())
    opening = bars.iloc[:3]
    side = 1 if float(bars.iloc[0]["open"]) > upper and bool((opening["close"] > upper).all()) else -1 if float(bars.iloc[0]["open"]) < lower and bool((opening["close"] < lower).all()) else 0
    if not side:
        return None
    for idx in range(3, min(len(bars) - 1, 24)):
        row = bars.iloc[idx]
        touched = float(row["low"]) <= float(row["ema8"]) if side > 0 else float(row["high"]) >= float(row["ema8"])
        rejected = float(row["close"]) > float(row["ema8"]) if side > 0 else float(row["close"]) < float(row["ema8"])
        if touched and rejected:
            return idx, side, float(row["low"]) if side > 0 else float(row["high"])
    return None


def _ema_break_retest(bars: pd.DataFrame, previous: pd.DataFrame | None) -> tuple[int, int, float] | None:
    if not _same_contract(bars, previous):
        return None
    upper, lower = float(previous["high"].max()), float(previous["low"].min())
    for idx in range(21, min(len(bars) - 1, 54)):
        row = bars.iloc[idx]
        side = 1 if float(row["ema8"]) > float(row["ema21"]) and float(row["close"]) > upper else -1 if float(row["ema8"]) < float(row["ema21"]) and float(row["close"]) < lower else 0
        if side:
            retest = _retest(bars, idx + 1, upper if side > 0 else lower, side)
            if retest is not None:
                retest_row = bars.iloc[retest]
                return retest, side, float(retest_row["low"]) if side > 0 else float(retest_row["high"])
    return None


def _vwap_pullback(bars: pd.DataFrame, previous: pd.DataFrame | None) -> tuple[int, int, float] | None:
    opening = bars.iloc[:3]
    span = float(opening["high"].max() - opening["low"].min())
    if span <= 0:
        return None
    move = float(opening.iloc[-1]["close"] - opening.iloc[0]["open"])
    if abs(move) / span < 0.65:
        return None
    side = 1 if move > 0 else -1
    for idx in range(3, min(len(bars) - 1, 24)):
        row = bars.iloc[idx]
        touched = float(row["low"]) <= float(row["vwap"]) if side > 0 else float(row["high"]) >= float(row["vwap"])
        rejected = float(row["close"]) > float(row["vwap"]) and float(row["close"]) > float(row["open"]) if side > 0 else float(row["close"]) < float(row["vwap"]) and float(row["close"]) < float(row["open"])
        if touched and rejected:
            return idx, side, float(row["low"]) if side > 0 else float(row["high"])
    return None


def _multi_indicator(bars: pd.DataFrame, previous: pd.DataFrame | None) -> tuple[int, int, float] | None:
    for idx in range(40, min(len(bars) - 1, 66)):
        prior, row = bars.iloc[idx - 1], bars.iloc[idx]
        bullish_extremes = sum([
            float(prior["close"]) < float(prior["ema10"]),
            float(prior["close"]) < float(prior["ema20"]),
            float(prior["close"]) < float(prior["ema50"]),
            float(prior["rsi14"]) < 30,
            float(prior["stoch14"]) < 20,
            float(prior["cci20"]) < -100,
            float(prior["momentum10"]) < 0 and float(prior["macd"]) < float(prior["macd_signal"]),
        ])
        bearish_extremes = sum([
            float(prior["close"]) > float(prior["ema10"]),
            float(prior["close"]) > float(prior["ema20"]),
            float(prior["close"]) > float(prior["ema50"]),
            float(prior["rsi14"]) > 70,
            float(prior["stoch14"]) > 80,
            float(prior["cci20"]) > 100,
            float(prior["momentum10"]) > 0 and float(prior["macd"]) > float(prior["macd_signal"]),
        ])
        if bullish_extremes >= 5 and float(row["close"]) > float(prior["high"]):
            return idx, 1, float(row["low"])
        if bearish_extremes >= 5 and float(row["close"]) < float(prior["low"]):
            return idx, -1, float(row["high"])
    return None


DETECTORS: dict[str, Callable[[pd.DataFrame, pd.DataFrame | None], tuple[int, int, float] | None]] = {
    "opening_range_breakout_retest": _opening_range,
    "prior_day_break_retest": _prior_break,
    "liquidity_sweep_mss_fvg": _sweep_mss_fvg,
    "first_touch_rsi_fade": _first_touch_rsi,
    "gap_continuation": _gap_continuation,
    "ema_8_21_break_retest": _ema_break_retest,
    "opening_drive_vwap_pullback": _vwap_pullback,
    "multi_indicator_reversal": _multi_indicator,
}


def simulate_intraday(bars: pd.DataFrame, signal: tuple[int, int, float], reward_risk: float, market: str) -> float | None:
    signal_idx, side, stop = signal
    entry_idx = signal_idx + 1
    if entry_idx >= len(bars) or bars.iloc[entry_idx]["time"] > "14:30":
        return None
    entry = float(bars.iloc[entry_idx]["open"])
    risk = side * (entry - stop)
    tick = 0.25 if market == "MES" else 0.01
    if risk < 2 * tick:
        return None
    if market == "MES" and risk / tick > 60:
        return None
    if market != "MES" and risk / entry > 0.02:
        return None
    target = entry + side * risk * reward_risk
    exit_price = float(bars.iloc[min(len(bars) - 1, entry_idx + MAX_HOLD_BARS)]["close"])
    for _, row in bars.iloc[entry_idx:min(len(bars), entry_idx + MAX_HOLD_BARS + 1)].iterrows():
        stop_hit = float(row["low"]) <= stop if side > 0 else float(row["high"]) >= stop
        target_hit = float(row["high"]) >= target if side > 0 else float(row["low"]) <= target
        if stop_hit:
            exit_price = stop
            break
        if target_hit:
            exit_price = target
            break
    points = side * (exit_price - entry)
    return points * 5.0 if market == "MES" else points * (ETF_NOTIONAL / entry)


def _metrics(gross: list[float], cost: float) -> dict[str, Any]:
    net = [value - cost for value in gross]
    if not net:
        return {"trades": 0, "expectancy": None, "profit_factor": None, "p_value": None}
    mean = sum(net) / len(net)
    variance = sum((value - mean) ** 2 for value in net) / max(1, len(net) - 1)
    standard_error = math.sqrt(variance / len(net)) if variance > 0 else 0.0
    t_stat = mean / standard_error if standard_error else (math.inf if mean > 0 else 0.0)
    p_value = 1.0 - NormalDist().cdf(t_stat) if math.isfinite(t_stat) else 0.0
    wins = sum(value for value in net if value > 0)
    losses = -sum(value for value in net if value <= 0)
    equity = pd.Series([0.0, *net]).cumsum()
    return {
        "trades": len(net),
        "total_pnl": round(sum(net), 2),
        "expectancy": round(mean, 4),
        "win_rate": round(sum(value > 0 for value in net) / len(net), 4),
        "profit_factor": round(wins / losses, 4) if losses else None,
        "max_drawdown": round(float((equity.cummax() - equity).max()), 2),
        "p_value": round(p_value, 8),
    }


def _split_dates(dates: list[str]) -> tuple[list[str], list[list[str]], dict[str, Any]]:
    development_end = int(len(dates) * 0.70)
    selection_end = int(len(dates) * 0.85)
    development = dates[:development_end]
    width = len(development) // 3
    regimes = [development[:width], development[width:2 * width], development[2 * width:]]
    sealed = {
        "selection": {"sessions": selection_end - development_end, "start": dates[development_end] if development_end < len(dates) else None, "opened": False},
        "final": {"sessions": len(dates) - selection_end, "start": dates[selection_end] if selection_end < len(dates) else None, "opened": False},
    }
    return development, regimes, sealed


def _survives(regimes: list[dict[str, Any]], aggregate: dict[str, Any], stress: dict[str, Any]) -> bool:
    return bool(
        all(row["trades"] >= 20 and (row["expectancy"] or 0) > 0 and (row["profit_factor"] or 0) > 1 for row in regimes)
        and (stress["expectancy"] or 0) > 0
        and (aggregate["p_value"] if aggregate["p_value"] is not None else 1) < BONFERRONI_ALPHA
    )


def _daily_signal(frame: pd.DataFrame, family: str) -> pd.Series:
    close = frame["close"]
    sma200 = close.rolling(200).mean()
    if family == "sma200_long_cash":
        return close > sma200
    if family == "sma5_20_cross":
        return close.rolling(5).mean() > close.rolling(20).mean()
    if family == "double7":
        enter = (close > sma200) & (close <= close.rolling(7).min())
        exit_signal = close >= close.rolling(7).max()
    elif family == "rsi2_200d":
        rsi2 = _rsi(close, 2)
        enter = (close > sma200) & (rsi2 < 10)
        exit_signal = rsi2 > 70
    elif family == "multi_ma_majority":
        votes = sum((close > close.rolling(period).mean()).astype(int) for period in (5, 10, 20, 50, 100, 200))
        enter = votes >= 5
        exit_signal = votes <= 2
    else:
        raise ValueError(f"unknown daily family: {family}")
    state = False
    values: list[bool] = []
    for timestamp in frame.index:
        if not state and bool(enter.loc[timestamp]):
            state = True
        elif state and bool(exit_signal.loc[timestamp]):
            state = False
        values.append(state)
    return pd.Series(values, index=frame.index)


def _daily_trades(frame: pd.DataFrame, family: str) -> list[tuple[str, float]]:
    desired = _daily_signal(frame, family).fillna(False)
    trades: list[tuple[str, float]] = []
    entry_price: float | None = None
    entry_date: str | None = None
    for idx in range(1, len(frame)):
        want = bool(desired.iloc[idx - 1])
        if entry_price is None and want:
            entry_price = float(frame.iloc[idx]["open"])
            entry_date = frame.index[idx].date().isoformat()
        elif entry_price is not None and not want:
            exit_price = float(frame.iloc[idx]["open"])
            trades.append((entry_date or frame.index[idx].date().isoformat(), ETF_NOTIONAL * (exit_price / entry_price - 1.0)))
            entry_price = entry_date = None
    if entry_price is not None:
        trades.append((entry_date or frame.index[-1].date().isoformat(), ETF_NOTIONAL * (float(frame.iloc[-1]["close"]) / entry_price - 1.0)))
    return trades


def run_tournament() -> dict[str, Any]:
    registry = build_registry()
    trials: list[dict[str, Any]] = []
    sealed_holdouts: dict[str, Any] = {}
    trial_lookup = {(row["horizon"], row["market"], row["family"], row["reward_risk"]): row["trial_id"] for row in registry["trials"]}

    for market, path in INTRADAY_PATHS.items():
        dates, sessions = load_intraday(path, market)
        development, regimes, sealed = _split_dates(dates)
        sealed_holdouts[f"{market}_intraday"] = sealed
        cost = MES_BASELINE_COST if market == "MES" else ETF_BASELINE_COST
        for family in INTRADAY_FAMILIES:
            dated_signals: list[tuple[str, tuple[int, int, float]]] = []
            date_position = {day: index for index, day in enumerate(dates)}
            for day in development:
                position = date_position[day]
                previous = sessions[dates[position - 1]] if position > 0 else None
                signal = DETECTORS[family](sessions[day], previous)
                if signal is None:
                    continue
                dated_signals.append((day, signal))
            for reward_risk in REWARD_RISKS:
                realized: list[tuple[str, float]] = []
                for day, signal in dated_signals:
                    gross = simulate_intraday(sessions[day], signal, reward_risk, market)
                    if gross is not None:
                        realized.append((day, gross))
                aggregate = _metrics([value for _, value in realized], cost)
                stress = _metrics([value for _, value in realized], cost * 2)
                regime_metrics = [_metrics([value for day, value in realized if day in set(regime)], cost) for regime in regimes]
                trials.append({
                    "trial_id": trial_lookup[("intraday_5m", market, family, reward_risk)],
                    "horizon": "intraday_5m",
                    "market": market,
                    "family": family,
                    "reward_risk": reward_risk,
                    "development": aggregate,
                    "development_2x_friction": stress,
                    "development_regimes": regime_metrics,
                    "development_survivor": _survives(regime_metrics, aggregate, stress),
                })

    for market, path in DAILY_PATHS.items():
        frame = pd.read_parquet(path).sort_index()
        frame.index = pd.to_datetime(frame.index)
        dates = [timestamp.date().isoformat() for timestamp in frame.index]
        development, regimes, sealed = _split_dates(dates)
        sealed_holdouts[f"{market}_daily"] = sealed
        development_set = set(development)
        for family in DAILY_FAMILIES:
            realized = [(day, gross) for day, gross in _daily_trades(frame, family) if day in development_set]
            aggregate = _metrics([value for _, value in realized], ETF_BASELINE_COST)
            stress = _metrics([value for _, value in realized], ETF_BASELINE_COST * 2)
            regime_metrics = [_metrics([value for day, value in realized if day in set(regime)], ETF_BASELINE_COST) for regime in regimes]
            trials.append({
                "trial_id": trial_lookup[("daily", market, family, None)],
                "horizon": "daily",
                "market": market,
                "family": family,
                "reward_risk": None,
                "development": aggregate,
                "development_2x_friction": stress,
                "development_regimes": regime_metrics,
                "development_survivor": _survives(regime_metrics, aggregate, stress),
            })

    ranked = sorted(trials, key=lambda row: row["development"]["expectancy"] if row["development"]["expectancy"] is not None else -math.inf, reverse=True)
    survivors = [row["trial_id"] for row in trials if row["development_survivor"]]
    return {
        "experiment": registry["experiment"],
        "specification": SPEC,
        "registry_sha256": registry["registry_sha256"],
        "source_ledger_sha256": registry["source_ledger_sha256"],
        "mode": "development_only_research",
        "execution_enabled": False,
        "can_submit_orders": False,
        "trial_count": len(trials),
        "effective_attempt_count": EFFECTIVE_ATTEMPTS,
        "bonferroni_alpha": BONFERRONI_ALPHA,
        "sealed_holdouts": sealed_holdouts,
        "development_survivors": survivors,
        "survivor_count": len(survivors),
        "top_20_by_development_expectancy": ranked[:20],
        "trials": trials,
        "verdict": "development_survivor_requires_shadow_review" if survivors else "no_corrected_development_survivor",
        "warning": "No result has execution or promotion authority. Social-media winners are not complete ledgers.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    registry = build_registry()
    args.registry.parent.mkdir(parents=True, exist_ok=True)
    args.registry.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    report = run_tournament()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.print_report:
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
