"""Causal, common-fabric BLSH scanner bake-off (shadow only)."""
from __future__ import annotations

import hashlib
import json
import math
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
    result = 100 - 100 / (1 + relative)
    result = result.mask((down == 0) & (up > 0), 100)
    return result.mask((down == 0) & (up == 0), 50)


def common_feature_fabric(rows: Iterable[Mapping[str, Any]] | pd.DataFrame) -> pd.DataFrame:
    bars = validate_ohlcv(rows)
    frames: list[pd.DataFrame] = []
    for _, group in bars.groupby("ticker", sort=True):
        frame = group.copy().sort_values("timestamp")
        close, volume = frame["close"], frame["volume"]
        typical = (frame["high"] + frame["low"] + close) / 3
        session = frame["timestamp"].dt.tz_convert("America/New_York").dt.date
        cumulative_volume = volume.groupby(session).cumsum().replace(0, np.nan)
        frame["vwap"] = (typical * volume).groupby(session).cumsum() / cumulative_volume
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


def lightgbm_predictions(fabric: pd.DataFrame, *, min_train_rows: int = 252, schedule: pd.DataFrame | None = None) -> pd.DataFrame:
    features = ["range_pos_5", "range_pos_20", "range_pos_60", "rsi_2", "rsi_14", "close_z20", "volume_ratio20", "true_range_pct", "return_1", "trend_20"]
    sides = pd.Series("ABSTAIN", index=fabric.index)
    scores = pd.Series(0.0, index=fabric.index)
    reasons = pd.Series("insufficient_purged_training_history", index=fabric.index)
    cutoffs = pd.Series(pd.NaT, index=fabric.index, dtype="datetime64[ns, UTC]")
    label_ends = cutoffs.copy()
    def emit():
        output = _emit(fabric, "lightgbm_blsh_v1", sides, scores, features)
        output["model_status"] = reasons
        output["training_cutoff"] = cutoffs
        output["training_label_max_ts"] = label_ends
        return output
    try:
        import lightgbm as lgb
    except ImportError:
        reasons[:] = "not_configured_lightgbm"
        return emit()
    try:
        labels = _market_outcomes(fabric, (5,), schedule=schedule)
    except ImportError:
        reasons[:] = "not_configured_exchange_calendar"
        return emit()
    base = fabric.merge(labels[["ticker", "timestamp", "forward_return_5", "outcome_ts_5"]], on=["ticker", "timestamp"], validate="one_to_one")
    base.index = fabric.index
    base = base.dropna(subset=features)
    # Global calendar-month folds across every ticker; label END must precede
    # the fold boundary. No prediction-time label is required for test rows.
    months = base.timestamp.dt.tz_localize(None).dt.to_period("M")
    for month in sorted(months.unique()):
        cutoff = month.start_time.tz_localize("UTC")
        train = base[(base.timestamp >= cutoff - pd.DateOffset(months=12)) & (base.timestamp < cutoff) & (base.outcome_ts_5 < cutoff)].dropna(subset=["forward_return_5"])
        test = base[months == month]
        if len(train) < min_train_rows or train.timestamp.min() > cutoff - pd.DateOffset(months=12) + pd.Timedelta(days=7):
            continue
        if (train.forward_return_5 > 0).nunique() < 2:
            reasons.loc[test.index] = "insufficient_target_classes"
            continue
        model = lgb.LGBMClassifier(n_estimators=100, max_depth=3, learning_rate=.03, random_state=7, verbosity=-1, n_jobs=1)
        model.fit(train[features], (train.forward_return_5 > 0).astype(int))
        probability = pd.Series(model.predict_proba(test[features])[:, 1], index=test.index)
        scores.loc[test.index] = (probability - .5).abs() * 2
        sides.loc[probability[probability >= .6].index] = "LONG"
        sides.loc[probability[probability <= .4].index] = "SHORT"
        reasons.loc[test.index] = "historical_walk_forward_not_live"
        cutoffs.loc[test.index] = cutoff
        label_ends.loc[test.index] = train.outcome_ts_5.max()
    return emit()


def _market_outcomes(bars: pd.DataFrame, horizons: tuple[int, ...], *, schedule: pd.DataFrame | None = None) -> pd.DataFrame:
    """T+n exchange-session CLOSE outcomes from bar-close-stamped 15m RTH bars.

    Every expected post-signal bar must exist. Missing a day cannot shorten a
    horizon. An explicit schedule is useful for audited provider calendars/tests.
    """
    prices = validate_ohlcv(bars)[["ticker", "timestamp", "close", "high", "low"]]
    if any(not isinstance(h, int) or h < 1 for h in horizons):
        raise ValueError("positive_session_horizons_required")
    if schedule is None:
        import pandas_market_calendars as mcal
        schedule = mcal.get_calendar("NYSE").schedule(start_date=prices.timestamp.min().date(), end_date=(prices.timestamp.max() + pd.Timedelta(days=max(horizons) * 3 + 10)).date())
    schedule = schedule.copy()
    for column in ("market_open", "market_close"):
        schedule[column] = pd.to_datetime(schedule[column], utc=True, errors="raise")
    schedule = schedule.sort_values("market_open").reset_index(drop=True)
    if schedule.empty or (schedule.market_close <= schedule.market_open).any() or schedule.market_open.duplicated().any() or (schedule.market_open.iloc[1:].reset_index(drop=True) <= schedule.market_close.iloc[:-1].reset_index(drop=True)).any():
        raise ValueError("invalid_exchange_schedule")
    expected = [pd.date_range(row.market_open + pd.Timedelta(minutes=15), row.market_close, freq="15min") for row in schedule.itertuples()]
    session_for_ts = {stamp: i for i, stamps in enumerate(expected) for stamp in stamps}
    for horizon in horizons:
        prices[f"forward_return_{horizon}"] = np.nan
        prices[f"underlying_max_return_{horizon}"] = np.nan
        prices[f"underlying_min_return_{horizon}"] = np.nan
        prices[f"outcome_ts_{horizon}"] = pd.Series(pd.NaT, index=prices.index, dtype="datetime64[ns, UTC]")
        prices[f"outcome_status_{horizon}"] = "signal_not_on_rth_bar_close"
    for _, group in prices.groupby("ticker"):
        lookup = group.set_index("timestamp")
        for index, row in group.iterrows():
            session = session_for_ts.get(row.timestamp)
            if session is None:
                continue
            for horizon in horizons:
                target = session + horizon
                status_col = f"outcome_status_{horizon}"
                prices.at[index, status_col] = "missing_future_session_or_bars"
                if target >= len(expected):
                    continue
                stamps = expected[session][expected[session] > row.timestamp]
                for future in expected[session + 1:target + 1]:
                    stamps = stamps.append(future)
                if not stamps.isin(lookup.index).all():
                    continue
                path = lookup.loc[stamps]
                prices.at[index, f"forward_return_{horizon}"] = path.iloc[-1].close / row.close - 1
                prices.at[index, f"underlying_max_return_{horizon}"] = path.high.max() / row.close - 1
                prices.at[index, f"underlying_min_return_{horizon}"] = path.low.min() / row.close - 1
                prices.at[index, f"outcome_ts_{horizon}"] = stamps[-1]
                prices.at[index, status_col] = "resolved"
    return prices


def join_forward_returns(predictions: pd.DataFrame, bars: pd.DataFrame, horizons: tuple[int, ...] = (1, 5, 10), *, schedule: pd.DataFrame | None = None) -> pd.DataFrame:
    validated = validate_scanner_output(predictions)
    prices = _market_outcomes(bars, horizons, schedule=schedule)
    merged = validated.merge(prices, left_on=["ticker", "ts"], right_on=["ticker", "timestamp"], how="left", validate="many_to_one")
    for horizon in horizons:
        high, low = merged[f"underlying_max_return_{horizon}"], merged[f"underlying_min_return_{horizon}"]
        merged[f"mfe_{horizon}"] = np.where(merged.side == "LONG", high.clip(lower=0), np.where(merged.side == "SHORT", (-low).clip(lower=0), np.nan))
        merged[f"mae_{horizon}"] = np.where(merged.side == "LONG", low.clip(upper=0), np.where(merged.side == "SHORT", (-high).clip(upper=0), np.nan))
        merged[f"outcome_status_{horizon}"] = merged[f"outcome_status_{horizon}"].fillna("missing_signal_bar")
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
            "live_prediction_timestamp_provenance_required",
            "benchmark_and_transaction_cost_returns_required",
            "multiple_testing_control_required",
            "dependence_robust_paired_statistic_required",
            "point_in_time_optionable_universe_required",
            "complete_hmm_ivr_breadth_feature_fabric_required",
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


def build_bakeoff(rows: Iterable[Mapping[str, Any]], *, as_of: datetime | None = None, schedule: pd.DataFrame | None = None) -> dict[str, Any]:
    observed_at = datetime.now(timezone.utc)
    cutoff = pd.Timestamp(as_of or observed_at)
    if cutoff.tzinfo is None:
        raise ValueError("as_of_timezone_required")
    bars = validate_ohlcv(rows)
    bars = bars[bars.timestamp <= cutoff]
    if bars.empty:
        raise ValueError("no_bars_available_as_of")
    fabric = common_feature_fabric(bars)
    predictions = pd.concat([arps_predictions(fabric), donchian_climax_predictions(fabric), lightgbm_predictions(fabric, schedule=schedule)], ignore_index=True)
    # Bulk historical regeneration is never proof of prospective collection.
    predictions["recorded_at"] = observed_at.isoformat()
    predictions["collection_mode"] = "historical_replay"
    predictions["live_evidence_eligible"] = False
    return {
        "schema_version": 1, "generated_at": (as_of or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z"),
        "status": "quarantined_research_predictions", "prediction_count": len(predictions),
        "statistical_gate": statistical_promotion_gate(pd.DataFrame()),
        "collection_mode": "historical_replay", "live_evidence_eligible": False,
        "feature_limitations": ["bar_windows_not_verified_daily_windows", "point_in_time_optionable_universe_unverified", "hmm_ivr_breadth_context_not_wired", "fixed_rule_weights_not_calibrated"],
        "scanner_counts": predictions.groupby("scanner_id").size().to_dict(),
        "predictions": predictions.assign(ts=predictions["ts"].astype(str)).to_dict("records"),
        "minimum_live_shadow_days": 63, **AUTHORITY,
    }
