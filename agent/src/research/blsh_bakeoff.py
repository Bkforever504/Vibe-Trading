"""Causal, common-fabric BLSH scanner bake-off (shadow only)."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd
from scipy.stats import norm

from contracts.schemas import validate_ohlcv, validate_scanner_output

AUTHORITY = {"execution_enabled": False, "can_submit_orders": False, "promotion_authority": "human_review_only"}
CORE_UNIVERSE = ("SPY", "QQQ", "IWM", "GLD", "TLT")


def liquid_universe(adv: Mapping[str, float], *, top_n: int = 50) -> list[str]:
    ranked = [symbol.upper() for symbol, value in sorted(adv.items(), key=lambda item: (-float(item[1]), item[0])) if math.isfinite(float(value)) and float(value) > 0]
    return list(dict.fromkeys([*CORE_UNIVERSE, *ranked[:top_n]]))


def _rsi(series: pd.Series, period: int) -> pd.Series:
    delta = series.diff()
    up, down = delta.clip(lower=0).rolling(period).mean(), (-delta.clip(upper=0)).rolling(period).mean()
    relative = up / down.replace(0, np.nan)
    return (100 - 100 / (1 + relative)).fillna(50)


def common_feature_fabric(rows: Iterable[Mapping[str, Any]] | pd.DataFrame) -> pd.DataFrame:
    bars = validate_ohlcv(rows)
    frames: list[pd.DataFrame] = []
    for _, group in bars.groupby("ticker", sort=True):
        frame = group.copy().sort_values("timestamp")
        close, volume = frame["close"], frame["volume"]
        typical = (frame["high"] + frame["low"] + close) / 3
        cumulative_volume = volume.cumsum().replace(0, np.nan)
        frame["vwap"] = (typical * volume).cumsum() / cumulative_volume
        for window in (5, 20, 60):
            low, high = close.rolling(window).min(), close.rolling(window).max()
            frame[f"range_pos_{window}"] = (close - low) / (high - low).replace(0, np.nan)
        frame["rsi_2"], frame["rsi_14"] = _rsi(close, 2), _rsi(close, 14)
        mean20, std20 = close.rolling(20).mean(), close.rolling(20).std(ddof=1)
        frame["close_z20"] = (close - mean20) / std20.replace(0, np.nan)
        frame["volume_ratio20"] = volume / volume.rolling(20).mean().replace(0, np.nan)
        frame["true_range_pct"] = (frame["high"] - frame["low"]) / close
        frame["return_1"] = close.pct_change()
        frame["trend_20"] = close.pct_change(20)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True).replace([np.inf, -np.inf], np.nan)


def _emit(frame: pd.DataFrame, scanner_id: str, side: pd.Series, score: pd.Series, features: list[str]) -> pd.DataFrame:
    output = pd.DataFrame({
        "ticker": frame["ticker"], "ts": frame["timestamp"], "scanner_id": scanner_id,
        "score": score.clip(0, 1).fillna(0), "side": side.fillna("ABSTAIN"),
        "features_json": frame[features].apply(lambda row: json.dumps({key: None if pd.isna(value) else round(float(value), 8) for key, value in row.items()}, sort_keys=True), axis=1),
    })
    output["features_hash"] = output["features_json"].map(lambda value: hashlib.sha256(value.encode()).hexdigest())
    output["execution_enabled"] = False
    output["can_submit_orders"] = False
    return validate_scanner_output(output)


def arps_predictions(fabric: pd.DataFrame) -> pd.DataFrame:
    low = (1 - fabric["range_pos_20"].fillna(.5)) * .35 + (1 - fabric["rsi_2"].fillna(50) / 100) * .25 + (-fabric["close_z20"].fillna(0)).clip(-3, 3) / 6 + .5
    trend_up = fabric["trend_20"].fillna(0) > 0
    raw = low.where(trend_up, np.nan)
    score = raw.groupby(fabric["timestamp"]).rank(pct=True).fillna(0)
    side = pd.Series(np.where((score >= .9) & trend_up, "LONG", "ABSTAIN"), index=fabric.index)
    return _emit(fabric, "arps_v1", side, score, ["range_pos_20", "rsi_2", "close_z20", "trend_20"])


def donchian_climax_predictions(fabric: pd.DataFrame) -> pd.DataFrame:
    low20 = fabric.groupby("ticker")["low"].transform(lambda s: s.rolling(20).min())
    high20 = fabric.groupby("ticker")["high"].transform(lambda s: s.rolling(20).max())
    climax = (fabric["volume_ratio20"] >= 2) & (fabric["true_range_pct"] >= fabric.groupby("ticker")["true_range_pct"].transform(lambda s: s.rolling(20).quantile(.8)))
    long = climax & (fabric["low"] <= low20)
    short = climax & (fabric["high"] >= high20)
    raw = ((fabric["volume_ratio20"].fillna(0) / 4).clip(0, 1) * .6 + climax.astype(float) * .4)
    score = raw.groupby(fabric["timestamp"]).rank(pct=True)
    side = pd.Series(np.select([long & (score >= .9), short & (score >= .9)], ["LONG", "SHORT"], default="ABSTAIN"), index=fabric.index)
    return _emit(fabric, "donchian_climax_v1", side, score, ["range_pos_20", "volume_ratio20", "true_range_pct"])


def lightgbm_predictions(fabric: pd.DataFrame, *, min_train_rows: int = 252) -> pd.DataFrame:
    features = ["range_pos_5", "range_pos_20", "range_pos_60", "rsi_2", "rsi_14", "close_z20", "volume_ratio20", "true_range_pct", "return_1", "trend_20"]
    base = fabric.dropna(subset=features).copy()
    if len(base) < min_train_rows + 21:
        return _emit(fabric, "lightgbm_blsh_v1", pd.Series("ABSTAIN", index=fabric.index), pd.Series(0.0, index=fabric.index), features)
    try:
        import lightgbm as lgb
    except ImportError:
        return _emit(fabric, "lightgbm_blsh_v1", pd.Series("ABSTAIN", index=fabric.index), pd.Series(0.0, index=fabric.index), features)
    base["target"] = base.groupby("ticker")["close"].shift(-5) / base["close"] - 1
    base = base.dropna(subset=["target"])
    split = max(min_train_rows, int(len(base) * .8))
    train, test = base.iloc[:split], base.iloc[split:]
    model = lgb.LGBMClassifier(n_estimators=100, max_depth=3, learning_rate=.03, random_state=7, verbosity=-1)
    model.fit(train[features], (train["target"] > 0).astype(int))
    probability = pd.Series(model.predict_proba(test[features])[:, 1], index=test.index)
    scores = pd.Series(0.0, index=fabric.index); scores.loc[probability.index] = (probability - .5).abs() * 2
    sides = pd.Series("ABSTAIN", index=fabric.index); sides.loc[probability[probability >= .6].index] = "LONG"; sides.loc[probability[probability <= .4].index] = "SHORT"
    return _emit(fabric, "lightgbm_blsh_v1", sides, scores, features)


def join_forward_returns(predictions: pd.DataFrame, bars: pd.DataFrame, horizons: tuple[int, ...] = (1, 5, 10)) -> pd.DataFrame:
    validated = validate_scanner_output(predictions)
    prices = validate_ohlcv(bars)[["ticker", "timestamp", "close", "high", "low"]]
    merged = validated.merge(prices, left_on=["ticker", "ts"], right_on=["ticker", "timestamp"], how="left")
    for horizon in horizons:
        merged[f"forward_return_{horizon}"] = merged.groupby("ticker")["close"].shift(-horizon) / merged["close"] - 1
        merged[f"mfe_{horizon}"] = merged.groupby("ticker")["high"].transform(lambda s: s.shift(-1).rolling(horizon).max().shift(-(horizon - 1))) / merged["close"] - 1
        merged[f"mae_{horizon}"] = merged.groupby("ticker")["low"].transform(lambda s: s.shift(-1).rolling(horizon).min().shift(-(horizon - 1))) / merged["close"] - 1
    return merged


def diebold_mariano(left: Iterable[float], right: Iterable[float]) -> dict[str, Any]:
    a, b = np.asarray(list(left), dtype=float), np.asarray(list(right), dtype=float)
    valid = np.isfinite(a) & np.isfinite(b)
    diff = a[valid] - b[valid]
    if len(diff) < 30 or np.std(diff, ddof=1) == 0:
        return {"status": "insufficient_data", "samples": int(len(diff)), **AUTHORITY}
    statistic = float(np.mean(diff) / (np.std(diff, ddof=1) / math.sqrt(len(diff))))
    return {"status": "observed", "samples": int(len(diff)), "statistic": round(statistic, 6), "p_value_two_sided": round(float(2 * norm.sf(abs(statistic))), 8), **AUTHORITY}


def statistical_promotion_gate(outcomes: pd.DataFrame, *, minimum_days: int = 63, minimum_predictions: int = 1000) -> dict[str, Any]:
    """Quarantine nominations until the end-to-end evidence contract is repaired.

    Row counts alone cannot prove live collection, purged labels, trading-day
    horizons, benchmark-relative net returns, or correction for trial selection.
    This block is unconditional: caller-supplied flags cannot bypass it.
    """
    return {
        "status": "blocked_validation_defects",
        "reason": "bakeoff_evidence_pipeline_requires_revalidation",
        "winner_candidate": None,
        "automatic_registry_change": False,
        "validation_blockers": [
            "global_time_split_and_label_purging_required",
            "trading_session_horizons_required",
            "scanner_independent_outcome_join_required",
            "live_prediction_timestamp_provenance_required",
            "benchmark_costs_and_multiple_testing_required",
            "dependence_robust_paired_statistic_required",
        ],
        **AUTHORITY,
    }


def _legacy_statistical_diagnostic(outcomes: pd.DataFrame, *, minimum_days: int = 63, minimum_predictions: int = 1000) -> dict[str, Any]:
    required = {"scanner_id", "ts", "excess_return"}
    if not required.issubset(outcomes.columns):
        return {"status": "insufficient_data", "reason": "required_outcome_columns_missing", **AUTHORITY}
    frame = outcomes.copy(); frame["ts"] = pd.to_datetime(frame["ts"], utc=True, errors="coerce")
    frame["excess_return"] = pd.to_numeric(frame["excess_return"], errors="coerce"); frame = frame.dropna(subset=["ts", "excess_return"])
    counts = frame.groupby("scanner_id").size().to_dict()
    days = int(frame["ts"].dt.normalize().nunique())
    if days < minimum_days or len(counts) < 2 or any(count < minimum_predictions for count in counts.values()):
        return {"status": "insufficient_data", "reason": "live_window_or_prediction_minimum_not_met", "trading_days": days, "counts": counts, **AUTHORITY}
    means = frame.groupby("scanner_id")["excess_return"].mean().sort_values(ascending=False)
    winner, runner_up = means.index[:2]
    paired = frame.pivot_table(index=["ts"], columns="scanner_id", values="excess_return", aggfunc="mean").dropna(subset=[winner, runner_up])
    comparison = diebold_mariano(paired[winner], paired[runner_up])
    nominate = comparison.get("status") == "observed" and comparison.get("p_value_two_sided", 1) < .05 and means[winner] > means[runner_up]
    return {
        "status": "human_review_nomination" if nominate else "no_statistical_winner",
        "winner_candidate": winner if nominate else None, "runner_up": runner_up,
        "mean_excess_returns": means.to_dict(), "paired_test": comparison,
        "automatic_registry_change": False, **AUTHORITY,
    }


def append_prediction_ledger(rows: pd.DataFrame, path: Path) -> int:
    validated = validate_scanner_output(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = pd.read_parquet(path) if path.exists() else pd.DataFrame()
    combined = pd.concat([existing, validated], ignore_index=True).drop_duplicates(["ticker", "ts", "scanner_id"], keep="first")
    temporary = path.with_suffix(path.suffix + ".tmp")
    combined.to_parquet(temporary, index=False)
    temporary.replace(path)
    return len(combined) - len(existing)


def build_bakeoff(rows: Iterable[Mapping[str, Any]], *, as_of: datetime | None = None) -> dict[str, Any]:
    fabric = common_feature_fabric(rows)
    predictions = pd.concat([arps_predictions(fabric), donchian_climax_predictions(fabric), lightgbm_predictions(fabric)], ignore_index=True)
    return {
        "schema_version": 1, "generated_at": (as_of or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z"),
        "status": "shadow_predictions_ready", "prediction_count": len(predictions),
        "scanner_counts": predictions.groupby("scanner_id").size().to_dict(),
        "predictions": predictions.assign(ts=predictions["ts"].astype(str)).to_dict("records"),
        "minimum_live_shadow_days": 63, **AUTHORITY,
    }
