#!/usr/bin/env python3
"""Point-in-time multi-asset market-scenario replay curriculum.

This module accelerates directional learning from historical bars while keeping
the final holdout and production execution isolated. It selects long, short, or
abstain from prior sessions only. Results measure underlying directional edge;
they are not a substitute for historical option NBBO replay.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import time, timedelta
from pathlib import Path
from statistics import median
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
NY = ZoneInfo("America/New_York")
OUTPUT_PATH = ROOT / "data" / "market_scenario_curriculum_results.json"
DEFAULT_DATASETS = {
    "SPY": ROOT / "data" / "liquid_edge_lab" / "spy_5m.parquet",
    "QQQ": ROOT / "data" / "liquid_edge_lab" / "qqq_5m.parquet",
    "IWM": ROOT / "data" / "liquid_edge_lab" / "iwm_5m.parquet",
}
CHECKPOINTS = ("10:30", "11:00", "12:00", "13:00", "14:00", "15:00")


@dataclass(frozen=True)
class CurriculumConfig:
    horizon_minutes: int = 60
    rolling_context_sessions: int = 20
    train_sessions: int = 504
    test_sessions: int = 126
    locked_holdout_sessions: int = 252
    minimum_train_episodes: int = 30
    base_round_trip_cost_bps: float = 4.0
    minimum_train_win_rate: float = 0.50
    minimum_review_oos_trades: int = 100
    minimum_review_holdout_trades: int = 30
    minimum_review_folds: int = 5
    minimum_profitable_fold_rate: float = 0.60


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _prepare_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"open", "high", "low", "close", "volume"}
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise ValueError("market bars require a DatetimeIndex")
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"market bars missing columns: {sorted(missing)}")
    clean = frame.loc[:, sorted(required)].copy()
    clean.index = (
        clean.index.tz_localize(NY)
        if clean.index.tz is None
        else clean.index.tz_convert(NY)
    )
    for column in required:
        clean[column] = pd.to_numeric(clean[column], errors="coerce")
    clean = clean.dropna(subset=list(required))
    clean = clean[~clean.index.duplicated(keep="last")].sort_index()
    return clean.between_time("09:30", "15:59")


def _checkpoint_stamp(session_day: Any, checkpoint: str) -> pd.Timestamp:
    hour, minute_ = (int(part) for part in checkpoint.split(":"))
    return pd.Timestamp.combine(session_day, time(hour, minute_)).tz_localize(NY)


def _regime(value: float, prior: list[float], *, low: float = 0.80, high: float = 1.25) -> str:
    if len(prior) < 5:
        return "unknown"
    baseline = median(prior)
    if baseline <= 0:
        return "unknown"
    ratio = value / baseline
    if ratio >= high:
        return "high"
    if ratio <= low:
        return "low"
    return "normal"


def _trend_state(history: pd.DataFrame) -> tuple[str, float, float, float]:
    typical = (history["high"] + history["low"] + history["close"]) / 3.0
    volume_sum = float(history["volume"].sum())
    vwap = float((typical * history["volume"]).sum() / volume_sum) if volume_sum > 0 else float(history["close"].iloc[-1])
    close = float(history["close"].iloc[-1])
    ema_fast = float(history["close"].ewm(span=5, adjust=False).mean().iloc[-1])
    ema_slow = float(history["close"].ewm(span=12, adjust=False).mean().iloc[-1])
    if close > vwap and ema_fast > ema_slow:
        state = "bull"
    elif close < vwap and ema_fast < ema_slow:
        state = "bear"
    else:
        state = "mixed"
    return state, vwap, ema_fast, ema_slow


def _opening_range_state(history: pd.DataFrame) -> str:
    opening = history.between_time("09:30", "09:59")
    if opening.empty:
        return "unknown"
    close = float(history["close"].iloc[-1])
    high = float(opening["high"].max())
    low = float(opening["low"].min())
    if close > high:
        return "above_or"
    if close < low:
        return "below_or"
    return "inside_or"


def _gap_state(session_open: float, previous_close: float | None) -> str:
    if previous_close is None or previous_close <= 0:
        return "unknown"
    gap = session_open / previous_close - 1.0
    if gap >= 0.0025:
        return "gap_up"
    if gap <= -0.0025:
        return "gap_down"
    return "flat"


def _bar_minutes(frame: pd.DataFrame) -> int:
    differences = frame.index.to_series().diff().dropna().dt.total_seconds().div(60)
    intraday = differences[(differences > 0) & (differences <= 30)]
    return max(1, int(round(float(intraday.median())))) if not intraday.empty else 5


def build_episodes(
    frame: pd.DataFrame,
    symbol: str,
    *,
    checkpoints: Iterable[str] = CHECKPOINTS,
    config: CurriculumConfig = CurriculumConfig(),
) -> list[dict[str, Any]]:
    """Build episodes with features frozen strictly before checkpoint entry."""
    bars = _prepare_frame(frame)
    interval_minutes = _bar_minutes(bars)
    minimum_future_bars = max(2, math.floor(config.horizon_minutes / interval_minutes * 0.80))
    prior_ranges: dict[str, list[float]] = defaultdict(list)
    prior_volumes: dict[str, list[float]] = defaultdict(list)
    previous_close: float | None = None
    episodes: list[dict[str, Any]] = []

    for session_day, day in bars.groupby(bars.index.date, sort=True):
        if day.empty:
            continue
        session_open = float(day["open"].iloc[0])
        for checkpoint in checkpoints:
            stamp = _checkpoint_stamp(session_day, checkpoint)
            history = day[day.index < stamp]
            if history.empty or stamp not in day.index:
                continue
            future_end = stamp + timedelta(minutes=config.horizon_minutes)
            future = day[(day.index >= stamp) & (day.index < future_end)]
            if len(future) < minimum_future_bars:
                continue

            trend, vwap, ema_fast, ema_slow = _trend_state(history)
            opening_state = _opening_range_state(history)
            observed_range = (float(history["high"].max()) - float(history["low"].min())) / session_open
            observed_volume = float(history["volume"].sum())
            range_state = _regime(observed_range, prior_ranges[checkpoint])
            volume_state = _regime(observed_volume, prior_volumes[checkpoint])
            gap_state = _gap_state(session_open, previous_close)
            scenario = f"trend={trend}|or={opening_state}|range={range_state}"

            entry = float(day.loc[stamp, "open"])
            exit_price = float(future["close"].iloc[-1])
            if entry <= 0 or exit_price <= 0:
                continue
            gross_long_bps = (exit_price / entry - 1.0) * 10_000.0
            episodes.append({
                "symbol": symbol.upper(),
                "date": session_day.isoformat(),
                "checkpoint_et": checkpoint,
                "feature_cutoff": history.index[-1].isoformat(),
                "entry_timestamp": stamp.isoformat(),
                "entry_basis": "checkpoint_bar_open_after_precheckpoint_features",
                "horizon_minutes": config.horizon_minutes,
                "scenario": scenario,
                "trend_state": trend,
                "opening_range_state": opening_state,
                "range_regime": range_state,
                "volume_regime": volume_state,
                "gap_state": gap_state,
                "vwap": round(vwap, 6),
                "ema_fast": round(ema_fast, 6),
                "ema_slow": round(ema_slow, 6),
                "entry_price": round(entry, 6),
                "exit_price": round(exit_price, 6),
                "gross_long_bps": round(gross_long_bps, 6),
                "gross_short_bps": round(-gross_long_bps, 6),
            })
            prior_ranges[checkpoint].append(observed_range)
            prior_volumes[checkpoint].append(observed_volume)
            keep = config.rolling_context_sessions
            prior_ranges[checkpoint] = prior_ranges[checkpoint][-keep:]
            prior_volumes[checkpoint] = prior_volumes[checkpoint][-keep:]
        previous_close = float(day["close"].iloc[-1])
    return episodes


def _policy_key(row: dict[str, Any]) -> str:
    return f"{row.get('symbol')}|{row.get('checkpoint_et')}|{row.get('scenario')}"


def _trim_top(values: list[float], fraction: float = 0.05) -> list[float]:
    if not values:
        return []
    remove = max(1, math.ceil(len(values) * fraction))
    return sorted(values)[:-remove]


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def train_policy(episodes: list[dict[str, Any]], config: CurriculumConfig) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in episodes:
        grouped[_policy_key(row)].append(row)
    policy: dict[str, dict[str, Any]] = {}
    base_cost = config.base_round_trip_cost_bps
    for key, rows in sorted(grouped.items()):
        candidates = []
        for action, field in (("long", "gross_long_bps"), ("short", "gross_short_bps")):
            gross = [float(row[field]) for row in rows if _number(row.get(field)) is not None]
            base = [value - base_cost for value in gross]
            doubled = [value - 2 * base_cost for value in gross]
            trimmed = _trim_top(base)
            win_rate = sum(value > 0 for value in base) / len(base) if base else 0.0
            robust = (
                len(base) >= config.minimum_train_episodes
                and (_mean(base) or 0.0) > 0
                and (_mean(doubled) or 0.0) > 0
                and (_mean(trimmed) or 0.0) > 0
                and win_rate >= config.minimum_train_win_rate
            )
            candidates.append({
                "action": action,
                "training_count": len(base),
                "training_expectancy_bps": round(_mean(base) or 0.0, 4),
                "training_double_cost_expectancy_bps": round(_mean(doubled) or 0.0, 4),
                "training_top5_removed_expectancy_bps": round(_mean(trimmed) or 0.0, 4),
                "training_win_rate": round(win_rate, 4),
                "robust": robust,
            })
        eligible = [row for row in candidates if row["robust"]]
        if eligible:
            selected = max(eligible, key=lambda row: row["training_expectancy_bps"])
            policy[key] = selected
    return policy


def _return_metrics(values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            "count": 0, "expectancy_bps": None, "win_rate": None,
            "profit_factor": None, "max_drawdown_bps": None,
            "top5_removed_expectancy_bps": None,
        }
    winners = [value for value in values if value > 0]
    losers = [-value for value in values if value < 0]
    equity = peak = max_drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    trimmed = _trim_top(values)
    return {
        "count": len(values),
        "expectancy_bps": round(sum(values) / len(values), 4),
        "win_rate": round(len(winners) / len(values), 4),
        "profit_factor": round(sum(winners) / sum(losers), 4) if losers else None,
        "max_drawdown_bps": round(max_drawdown, 4),
        "top5_removed_expectancy_bps": round(_mean(trimmed) or 0.0, 4),
    }


def apply_policy(
    episodes: list[dict[str, Any]],
    policy: dict[str, dict[str, Any]],
    config: CurriculumConfig,
) -> tuple[dict[str, Any], dict[str, Any]]:
    returns: dict[str, Any] = {"base": [], "double_cost": [], "triple_cost": [], "decisions": []}
    traded_by_symbol: dict[str, int] = defaultdict(int)
    scenario_counts: dict[str, int] = defaultdict(int)
    for row in sorted(episodes, key=lambda item: (str(item.get("date")), str(item.get("entry_timestamp")), str(item.get("symbol")))):
        selected = policy.get(_policy_key(row))
        if not selected:
            continue
        action = str(selected["action"])
        gross = float(row[f"gross_{action}_bps"])
        returns["base"].append(gross - config.base_round_trip_cost_bps)
        returns["double_cost"].append(gross - 2 * config.base_round_trip_cost_bps)
        returns["triple_cost"].append(gross - 3 * config.base_round_trip_cost_bps)
        returns["decisions"].append({
            "date": row.get("date"),
            "symbol": row.get("symbol"),
            "checkpoint_et": row.get("checkpoint_et"),
            "scenario": row.get("scenario"),
            "policy_key": _policy_key(row),
            "action": action,
            "base_return_bps": gross - config.base_round_trip_cost_bps,
            "double_cost_return_bps": gross - 2 * config.base_round_trip_cost_bps,
            "triple_cost_return_bps": gross - 3 * config.base_round_trip_cost_bps,
        })
        traded_by_symbol[str(row["symbol"])] += 1
        scenario_counts[_policy_key(row)] += 1
    total = len(episodes)
    traded = len(returns["base"])
    summary = {
        "episode_count": total,
        "traded_count": traded,
        "abstained_count": total - traded,
        "abstention_rate": round((total - traded) / total, 4) if total else 1.0,
        "selected_policy_count": len(policy),
        "base": _return_metrics(returns["base"]),
        "double_cost": _return_metrics(returns["double_cost"]),
        "triple_cost": _return_metrics(returns["triple_cost"]),
        "traded_by_symbol": dict(sorted(traded_by_symbol.items())),
        "most_used_scenarios": [
            {"policy_key": key, "trades": count}
            for key, count in sorted(scenario_counts.items(), key=lambda item: (-item[1], item[0]))[:20]
        ],
    }
    return summary, returns


def _scenario_attribution(decisions: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in decisions:
        grouped[(str(row.get("policy_key")), str(row.get("action")))].append(row)
    rows = []
    for (policy_key, action), items in grouped.items():
        base = [float(row["base_return_bps"]) for row in items]
        doubled = [float(row["double_cost_return_bps"]) for row in items]
        tripled = [float(row["triple_cost_return_bps"]) for row in items]
        folds = sorted({int(row["fold"]) for row in items if row.get("fold") is not None})
        row = {
            "policy_key": policy_key,
            "action": action,
            "count": len(items),
            "fold_count": len(folds),
            "folds": folds,
            "base": _return_metrics(base),
            "double_cost": _return_metrics(doubled),
            "triple_cost": _return_metrics(tripled),
        }
        row["diagnostic_survivor"] = (
            len(items) >= 30
            and len(folds) >= 2
            and (row["base"]["expectancy_bps"] or 0.0) > 0
            and (row["double_cost"]["expectancy_bps"] or 0.0) > 0
            and (row["base"]["top5_removed_expectancy_bps"] or 0.0) > 0
        )
        row["recurring_failure"] = len(items) >= 20 and (row["base"]["expectancy_bps"] or 0.0) < 0
        rows.append(row)
    rows.sort(key=lambda row: ((row["base"]["expectancy_bps"] or -1e9), row["count"]), reverse=True)
    return {
        "authority": "diagnostic_only_new_trials_required",
        "tested_scenario_action_count": len(rows),
        "diagnostic_survivors": [row for row in rows if row["diagnostic_survivor"]],
        "recurring_failures": sorted(
            [row for row in rows if row["recurring_failure"]],
            key=lambda row: (row["base"]["expectancy_bps"], -row["count"]),
        ),
        "all": rows,
    }


def _policy_fingerprint(policy: dict[str, dict[str, Any]]) -> str:
    frozen = {key: value.get("action") for key, value in sorted(policy.items())}
    return hashlib.sha256(json.dumps(frozen, sort_keys=True).encode("utf-8")).hexdigest()


def run_curriculum(
    episodes: list[dict[str, Any]],
    *,
    config: CurriculumConfig = CurriculumConfig(),
) -> dict[str, Any]:
    ordered = sorted(episodes, key=lambda row: (str(row.get("date")), str(row.get("entry_timestamp")), str(row.get("symbol"))))
    dates = sorted({str(row.get("date")) for row in ordered if row.get("date")})
    holdout_size = min(config.locked_holdout_sessions, max(0, len(dates) - config.train_sessions - config.test_sessions))
    development_dates = dates[:-holdout_size] if holdout_size else dates
    holdout_dates = dates[-holdout_size:] if holdout_size else []
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in ordered:
        by_date[str(row.get("date"))].append(row)

    folds = []
    aggregate: dict[str, Any] = {"base": [], "double_cost": [], "triple_cost": [], "decisions": []}
    cursor = config.train_sessions
    while cursor + config.test_sessions <= len(development_dates):
        train_dates = development_dates[cursor - config.train_sessions:cursor]
        test_dates = development_dates[cursor:cursor + config.test_sessions]
        train_rows = [row for day in train_dates for row in by_date[day]]
        test_rows = [row for day in test_dates for row in by_date[day]]
        policy = train_policy(train_rows, config)
        score, raw = apply_policy(test_rows, policy, config)
        for decision in raw["decisions"]:
            decision["fold"] = len(folds) + 1
        for key in ("base", "double_cost", "triple_cost", "decisions"):
            aggregate[key].extend(raw[key])
        folds.append({
            "fold": len(folds) + 1,
            "train_start": train_dates[0],
            "train_end": train_dates[-1],
            "test_start": test_dates[0],
            "test_end": test_dates[-1],
            "train_sessions": len(train_dates),
            "test_sessions": len(test_dates),
            "policy_fingerprint": _policy_fingerprint(policy),
            "result": score,
        })
        cursor += config.test_sessions

    development_rows = [row for day in development_dates for row in by_date[day]]
    final_policy = train_policy(development_rows, config)
    holdout_rows = [row for day in holdout_dates for row in by_date[day]]
    holdout_score, _ = apply_policy(holdout_rows, final_policy, config)
    aggregate_score = {
        "base": _return_metrics(aggregate["base"]),
        "double_cost": _return_metrics(aggregate["double_cost"]),
        "triple_cost": _return_metrics(aggregate["triple_cost"]),
    }
    scenario_attribution = _scenario_attribution(aggregate["decisions"])
    traded_folds = [fold for fold in folds if fold["result"]["traded_count"] > 0]
    profitable_folds = sum((fold["result"]["base"]["expectancy_bps"] or 0.0) > 0 for fold in traded_folds)
    profitable_fold_rate = profitable_folds / len(traded_folds) if traded_folds else 0.0
    checks = {
        "minimum_folds": len(folds) >= config.minimum_review_folds,
        "minimum_oos_trades": aggregate_score["base"]["count"] >= config.minimum_review_oos_trades,
        "profitable_fold_rate": profitable_fold_rate >= config.minimum_profitable_fold_rate,
        "oos_base_positive": (aggregate_score["base"]["expectancy_bps"] or 0.0) > 0,
        "oos_double_cost_positive": (aggregate_score["double_cost"]["expectancy_bps"] or 0.0) > 0,
        "oos_triple_cost_positive": (aggregate_score["triple_cost"]["expectancy_bps"] or 0.0) > 0,
        "oos_top5_removed_positive": (aggregate_score["base"]["top5_removed_expectancy_bps"] or 0.0) > 0,
        "minimum_locked_holdout_trades": holdout_score["traded_count"] >= config.minimum_review_holdout_trades,
        "locked_holdout_base_positive": (holdout_score["base"]["expectancy_bps"] or 0.0) > 0,
        "locked_holdout_double_cost_positive": (holdout_score["double_cost"]["expectancy_bps"] or 0.0) > 0,
    }
    passed = all(checks.values())
    return {
        "provider": "market_scenario_curriculum",
        "mode": "read_only_historical_directional_replay",
        "execution_enabled": False,
        "can_submit_orders": False,
        "promotion_authority": "human_review_only" if passed else "blocked",
        "scope": "underlying_directional_edge_only_not_historical_option_nbbo",
        "config": asdict(config),
        "episode_count": len(ordered),
        "date_count": len(dates),
        "date_start": dates[0] if dates else None,
        "date_end": dates[-1] if dates else None,
        "development_end": development_dates[-1] if development_dates else None,
        "locked_holdout_start": holdout_dates[0] if holdout_dates else None,
        "walk_forward_folds": folds,
        "walk_forward_summary": {
            "fold_count": len(folds),
            "traded_fold_count": len(traded_folds),
            "profitable_fold_count": profitable_folds,
            "profitable_fold_rate": round(profitable_fold_rate, 4),
            **aggregate_score,
        },
        "scenario_attribution": scenario_attribution,
        "locked_holdout": {
            "session_count": len(holdout_dates),
            "start": holdout_dates[0] if holdout_dates else None,
            "end": holdout_dates[-1] if holdout_dates else None,
            "policy_fingerprint": _policy_fingerprint(final_policy),
            "result": holdout_score,
        },
        "final_policy": {
            "selected_scenario_count": len(final_policy),
            "fingerprint": _policy_fingerprint(final_policy),
            "selected": final_policy,
        },
        "review_gate": {"passed": passed, "checks": checks},
        "warnings": [
            "The replay never searches the locked holdout and cannot enable execution.",
            "Underlying-bar directional edge does not prove option profitability; historical NBBO replay is still required.",
            "Unseen, sparse, or cost-fragile scenarios map to abstain.",
            "Post-hoc scenario survivors are diagnostic leads, not approved rules; each requires a new preregistered forward trial.",
            "Repeated parameter searching against this report would invalidate the holdout and requires a new preregistered dataset.",
        ],
    }


def _load_datasets(paths: dict[str, Path]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    episodes: list[dict[str, Any]] = []
    provenance = {}
    for symbol, path in paths.items():
        frame = pd.read_parquet(path)
        symbol_episodes = build_episodes(frame, symbol)
        episodes.extend(symbol_episodes)
        provenance[symbol] = {
            "path": str(path),
            "bar_count": len(frame),
            "episode_count": len(symbol_episodes),
            "start": str(frame.index.min()),
            "end": str(frame.index.max()),
        }
    return episodes, provenance


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    episodes, provenance = _load_datasets(DEFAULT_DATASETS)
    report = run_curriculum(episodes)
    report["datasets"] = provenance
    _write_json(args.output, report)
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        summary = report["walk_forward_summary"]
        holdout = report["locked_holdout"]["result"]
        print(
            f"episodes={report['episode_count']} folds={summary['fold_count']} "
            f"oos_trades={summary['base']['count']} oos_ev_bps={summary['base']['expectancy_bps']} "
            f"holdout_trades={holdout['traded_count']} holdout_ev_bps={holdout['base']['expectancy_bps']} "
            f"gate={report['review_gate']['passed']}"
        )


if __name__ == "__main__":
    main()
