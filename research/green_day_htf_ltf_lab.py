#!/usr/bin/env python3
"""Read-only reconstruction of green Flip/options days and HTF/LTF tests."""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import defaultdict
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.accelerated_bot_learning_report import _shadow_trades
from scripts.closed_trade_postmortem import dedupe_options_trade_records
from scripts import lifecycle_normalizer as canon

VIBE_HOME = Path.home() / ".vibe-trading"
FLIP_PATH = VIBE_HOME / "flip-trades.json"
OPTIONS_PATH = VIBE_HOME / "options-trades.json"
SHADOW_PATH = ROOT / "data" / "flip_shadow_candidates_log.jsonl"
MINUTE_PATH = ROOT / "data" / "spy_1m_edge_lab.parquet"
DAILY_DIR = ROOT / "data" / "htf_volume_screen_lab"
OUTPUT_PATH = ROOT / "data" / "green_day_htf_ltf_results.json"

CHECKPOINTS = ("10:30", "11:30", "12:00")
VARIANTS = (
    "ltf_only",
    "daily_aligned",
    "weekly_aligned",
    "daily_weekly_aligned",
    "daily_weekly_nonopposed",
    "all_three_aligned",
)
ROUND_TRIP_BPS = 2.0
BRACKET_BPS = 25.0


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return default


def _safe_float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _daily_path(symbol: str) -> Path | None:
    matches = sorted(DAILY_DIR.glob(f"{symbol.lower()}_*.parquet"))
    return matches[-1] if matches else None


def load_daily(symbol: str) -> pd.DataFrame | None:
    path = _daily_path(symbol)
    if path is None:
        return None
    frame = pd.read_parquet(path).copy()
    frame.columns = [str(column).lower() for column in frame.columns]
    frame.index = pd.to_datetime(frame.index).tz_localize(None).normalize()
    return frame.sort_index()


def _state(close: float, average: float, previous_average: float) -> str:
    if not all(np.isfinite(value) for value in (close, average, previous_average)):
        return "unavailable"
    if close > average and average > previous_average:
        return "bullish"
    if close < average and average < previous_average:
        return "bearish"
    return "mixed"


def build_htf_table(frame: pd.DataFrame) -> dict[str, pd.Series]:
    """Build states indexed by completed period end; callers enforce as-of."""
    daily_close = frame["close"].astype(float)
    daily_ma = daily_close.rolling(20, min_periods=20).mean()
    daily = pd.Series(
        [_state(c, m, p) for c, m, p in zip(daily_close, daily_ma, daily_ma.shift(5))],
        index=frame.index,
        dtype="object",
    )
    weekly_close = daily_close.resample("W-FRI").last().dropna()
    weekly_ma = weekly_close.rolling(20, min_periods=20).mean()
    weekly = pd.Series(
        [_state(c, m, p) for c, m, p in zip(weekly_close, weekly_ma, weekly_ma.shift(5))],
        index=weekly_close.index,
        dtype="object",
    )
    monthly_close = daily_close.resample("ME").last().dropna()
    monthly_ma = monthly_close.rolling(10, min_periods=10).mean()
    monthly = pd.Series(
        [_state(c, m, p) for c, m, p in zip(monthly_close, monthly_ma, monthly_ma.shift(3))],
        index=monthly_close.index,
        dtype="object",
    )
    return {"daily": daily, "weekly": weekly, "monthly": monthly}


def asof_states(table: dict[str, pd.Series], session_date: date | str) -> dict[str, str]:
    """Return only states from periods completed strictly before session_date."""
    stamp = pd.Timestamp(session_date).normalize()
    result: dict[str, str] = {}
    for frequency, series in table.items():
        eligible = series[series.index < stamp]
        result[frequency] = str(eligible.iloc[-1]) if not eligible.empty else "unavailable"
    return result


def direction_matches(state: str, direction: str) -> bool:
    expected = "bullish" if direction == "bull" else "bearish"
    return state == expected


def variant_allows(variant: str, states: dict[str, str], direction: str) -> bool:
    opposite = "bearish" if direction == "bull" else "bullish"
    if variant == "ltf_only":
        return True
    if variant == "daily_aligned":
        return direction_matches(states["daily"], direction)
    if variant == "weekly_aligned":
        return direction_matches(states["weekly"], direction)
    if variant == "daily_weekly_aligned":
        return all(direction_matches(states[key], direction) for key in ("daily", "weekly"))
    if variant == "daily_weekly_nonopposed":
        return all(states[key] != opposite for key in ("daily", "weekly"))
    if variant == "all_three_aligned":
        return all(direction_matches(states[key], direction) for key in ("daily", "weekly", "monthly"))
    raise ValueError(f"Unknown variant: {variant}")


def fresh_pullback(frame: pd.DataFrame, direction: str, lookback: int = 8, tolerance_bps: float = 8.0) -> bool:
    if len(frame) < 4:
        return False
    prior = frame.iloc[max(0, len(frame) - lookback - 1):-1]
    if prior.empty:
        return False
    tolerance = tolerance_bps / 10_000.0
    current, previous = frame.iloc[-1], frame.iloc[-2]
    if direction == "bull":
        support = prior[["vwap", "ema50"]].max(axis=1)
        touched = ((prior["low"] <= support * (1 + tolerance)) & (prior["high"] >= support * (1 - tolerance))).any()
        confirmed = (
            current["close"] > current["vwap"]
            and current["close"] > current["ema50"]
            and current["close"] > previous["close"]
            and current["close"] >= current["open"]
        )
    else:
        resistance = prior[["vwap", "ema50"]].min(axis=1)
        touched = ((prior["high"] >= resistance * (1 - tolerance)) & (prior["low"] <= resistance * (1 + tolerance))).any()
        confirmed = (
            current["close"] < current["vwap"]
            and current["close"] < current["ema50"]
            and current["close"] < previous["close"]
            and current["close"] <= current["open"]
        )
    return bool(touched and confirmed)


def compute_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    """Session VWAP and EMA50 exactly as ltf_signal consumes them.

    Exposed so a parity test can compare these values against the production
    flip bot's indicator math on identical bars.
    """
    work = frame.copy()
    typical = (work["high"] + work["low"] + work["close"]) / 3.0
    work["vwap"] = (typical * work["volume"]).cumsum() / work["volume"].cumsum().replace(0, np.nan)
    work["ema50"] = work["close"].ewm(span=50, adjust=False).mean()
    return work


def ltf_signal(frame: pd.DataFrame) -> dict[str, Any] | None:
    """Mirror the production 9-point VWAP/EMA recipe on completed bars."""
    if len(frame) < 55 or float(frame["volume"].sum()) <= 0:
        return None
    work = compute_indicators(frame)
    current = work.iloc[-1]
    ema_previous = work["ema50"].iloc[-6]
    session_open = float(work["open"].iloc[0])
    candidates = []
    for direction in ("bull", "bear"):
        if direction == "bull":
            distance = (current["close"] - current["vwap"]) / current["vwap"]
            checks = (
                (current["close"] > current["vwap"], 2),
                (current["close"] > current["ema50"], 2),
                (current["ema50"] > ema_previous, 1),
                (current["close"] > session_open, 1),
                (0 <= distance <= 0.015, 2),
                (fresh_pullback(work, direction), 1),
            )
        else:
            distance = (current["vwap"] - current["close"]) / current["vwap"]
            checks = (
                (current["close"] < current["vwap"], 2),
                (current["close"] < current["ema50"], 2),
                (current["ema50"] < ema_previous, 1),
                (current["close"] < session_open, 1),
                (0 <= distance <= 0.015, 2),
                (fresh_pullback(work, direction), 1),
            )
        score = sum(points for passed, points in checks if passed)
        if score == 9:
            candidates.append({
                "direction": direction,
                "score": score,
                "close": round(float(current["close"]), 4),
                "vwap": round(float(current["vwap"]), 4),
                "ema50": round(float(current["ema50"]), 4),
                "vwap_distance_pct": round(float(distance) * 100, 4),
            })
    return candidates[0] if len(candidates) == 1 else None


def _directional_bps(entry: float, exit_price: float, direction: str) -> float:
    raw = (exit_price / entry - 1.0) * 10_000
    return raw if direction == "bull" else -raw


def bracket_outcome(path: pd.DataFrame, entry: float, direction: str) -> float:
    target = entry * (1 + BRACKET_BPS / 10_000) if direction == "bull" else entry * (1 - BRACKET_BPS / 10_000)
    stop = entry * (1 - BRACKET_BPS / 10_000) if direction == "bull" else entry * (1 + BRACKET_BPS / 10_000)
    for _, bar in path.iterrows():
        stop_hit = bar["low"] <= stop if direction == "bull" else bar["high"] >= stop
        target_hit = bar["high"] >= target if direction == "bull" else bar["low"] <= target
        if stop_hit:
            return -BRACKET_BPS - ROUND_TRIP_BPS
        if target_hit:
            return BRACKET_BPS - ROUND_TRIP_BPS
    return _directional_bps(entry, float(path["close"].iloc[-1]), direction) - ROUND_TRIP_BPS


def _complete_window(frame: pd.DataFrame, end_hhmm: str = "13:44") -> bool:
    end_h, end_m = (int(part) for part in end_hhmm.split(":"))
    expected = pd.date_range(
        f"{frame.index[0].date()} 09:30",
        f"{frame.index[0].date()} {end_hhmm}",
        freq="1min",
        tz="America/New_York",
    )
    window = frame.loc[
        (frame.index.time >= time(9, 30)) & (frame.index.time <= time(end_h, end_m))
    ]
    return len(window.index.intersection(expected)) == len(expected)


def _complete_session(frame: pd.DataFrame) -> bool:
    return _complete_window(frame, "13:44")


def _checkpoint_window_end(checkpoint: str) -> str:
    hour, minute_ = (int(part) for part in checkpoint.split(":"))
    total = hour * 60 + minute_ + 59
    return f"{total // 60:02d}:{total % 60:02d}"


def replay_spy(
    minute: pd.DataFrame,
    htf: dict[str, pd.Series],
    completeness: str = "full_1345",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    minute = minute.copy()
    if minute.index.tz is None:
        minute.index = minute.index.tz_localize("America/New_York")
    else:
        minute.index = minute.index.tz_convert("America/New_York")
    minute.columns = [str(column).lower() for column in minute.columns]
    if completeness not in ("full_1345", "per_checkpoint"):
        raise ValueError(f"Unknown completeness mode: {completeness}")
    rows: list[dict[str, Any]] = []
    total_sessions = 0
    complete_sessions = 0
    per_checkpoint_eligible = {checkpoint: 0 for checkpoint in CHECKPOINTS}
    for session_date, raw in minute.groupby(minute.index.date):
        rth = raw.between_time("09:30", "15:59").sort_index()
        if rth.empty:
            continue
        total_sessions += 1
        session_complete_1345 = _complete_session(rth)
        if completeness == "full_1345" and not session_complete_1345:
            continue
        if session_complete_1345:
            complete_sessions += 1
        states = asof_states(htf, session_date)
        for checkpoint in CHECKPOINTS:
            if completeness == "per_checkpoint":
                if not _complete_window(rth, _checkpoint_window_end(checkpoint)):
                    continue
                per_checkpoint_eligible[checkpoint] += 1
            checkpoint_stamp = pd.Timestamp(f"{session_date} {checkpoint}", tz="America/New_York")
            history = rth[rth.index < checkpoint_stamp]
            signal = ltf_signal(history)
            if signal is None or checkpoint_stamp not in rth.index:
                continue
            future = rth[rth.index >= checkpoint_stamp]
            first_hour = future.iloc[:60]
            hard_exit = rth[rth.index < pd.Timestamp(f"{session_date} 13:45", tz="America/New_York")]
            if len(first_hour) < 60 or hard_exit.empty:
                continue
            entry = float(rth.loc[checkpoint_stamp, "open"])
            hour_bps = _directional_bps(entry, float(first_hour["close"].iloc[-1]), signal["direction"]) - ROUND_TRIP_BPS
            # The 13:45 hard-exit metric is only trustworthy when the session
            # is complete through 13:44; otherwise it is withheld as None.
            hard_bps = (
                _directional_bps(entry, float(hard_exit["close"].iloc[-1]), signal["direction"]) - ROUND_TRIP_BPS
                if session_complete_1345
                else None
            )
            bracket_bps = bracket_outcome(first_hour, entry, signal["direction"])
            for variant in VARIANTS:
                if variant_allows(variant, states, signal["direction"]):
                    rows.append({
                        "date": str(session_date),
                        "checkpoint_et": checkpoint,
                        "variant": variant,
                        "direction": signal["direction"],
                        "entry": round(entry, 4),
                        "states": states,
                        "signal": signal,
                        "return_60m_bps": round(hour_bps, 3),
                        "return_to_1345_bps": round(hard_bps, 3) if hard_bps is not None else None,
                        "bracket_25bps_return_bps": round(bracket_bps, 3),
                    })
    coverage = {
        "completeness_mode": completeness,
        "raw_sessions": total_sessions,
        "complete_through_1345_sessions": complete_sessions,
        "coverage_rate": round(complete_sessions / total_sessions, 4) if total_sessions else 0.0,
        "rule": (
            "all 1-minute bars present from 09:30 through 13:44 ET"
            if completeness == "full_1345"
            else "all 1-minute bars present from 09:30 through checkpoint+59m ET, per checkpoint"
        ),
    }
    if completeness == "per_checkpoint":
        coverage["per_checkpoint_eligible_sessions"] = per_checkpoint_eligible
    return rows, coverage


def _profit_factor(values: np.ndarray) -> float | str | None:
    wins, losses = values[values > 0], values[values < 0]
    if not len(losses):
        return "inf" if len(wins) else None
    return round(float(wins.sum() / abs(losses.sum())), 3)


def _block_bootstrap(values: np.ndarray, seed: int = 20260725) -> list[float | None]:
    if len(values) < 20:
        return [None, None]
    block = min(5, len(values))
    starts = np.arange(0, len(values) - block + 1)
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(3000):
        chunks = [values[start:start + block] for start in rng.choice(starts, math.ceil(len(values) / block), replace=True)]
        means.append(float(np.concatenate(chunks)[:len(values)].mean()))
    return [round(float(np.quantile(means, 0.025)), 3), round(float(np.quantile(means, 0.975)), 3)]


def metrics(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    values = np.asarray(
        [float(row[field]) for row in rows if row.get(field) is not None], dtype=float
    )
    if not len(values):
        return {"count": 0, "expectancy": None, "win_rate": None, "profit_factor": None}
    equity = np.cumsum(values)
    peak = np.maximum.accumulate(np.concatenate(([0.0], equity)))[1:]
    remove = max(1, math.ceil(len(values) * 0.01))
    trimmed = np.sort(values)[:-remove] if len(values) > 1 else np.asarray([])
    ci = _block_bootstrap(values)
    return {
        "count": int(len(values)),
        "expectancy": round(float(values.mean()), 3),
        "win_rate": round(float((values > 0).mean()), 4),
        "profit_factor": _profit_factor(values),
        "net": round(float(values.sum()), 3),
        "max_drawdown": round(float((equity - peak).min()), 3),
        "top_one_pct_removed_expectancy": round(float(trimmed.mean()), 3) if len(trimmed) else None,
        "block_bootstrap_ci95": ci,
        # A None CI means n < 20; downstream text must not invent an interval.
        "ci_status": "ok" if ci[0] is not None else "insufficient_n",
    }


def _window(value: str) -> str:
    year = int(value[:4])
    if year <= 2023:
        return "development_2022_2023"
    if year == 2024:
        return "selection_2024"
    return "diagnostic_consumed_2025_plus"


def summarize_replay(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for checkpoint in CHECKPOINTS:
        result[checkpoint] = {}
        for variant in VARIANTS:
            selected = [row for row in rows if row["checkpoint_et"] == checkpoint and row["variant"] == variant]
            result[checkpoint][variant] = {
                window: {
                    "return_60m_bps": metrics([row for row in selected if _window(row["date"]) == window], "return_60m_bps"),
                    "return_to_1345_bps": metrics([row for row in selected if _window(row["date"]) == window], "return_to_1345_bps"),
                    "bracket_25bps_return_bps": metrics([row for row in selected if _window(row["date"]) == window], "bracket_25bps_return_bps"),
                }
                for window in ("development_2022_2023", "selection_2024", "diagnostic_consumed_2025_plus")
            }
    return result


def _entry_time(row: dict[str, Any]) -> str | None:
    quality = row.get("entry_quality") or {}
    if quality.get("entry_minute_et"):
        return str(quality["entry_minute_et"])
    raw = row.get("entry_at")
    if not raw:
        return None
    stamp = pd.Timestamp(raw)
    return stamp.tz_convert("America/New_York").strftime("%H:%M") if stamp.tzinfo else None


def actual_flip_reconstruction(minute: pd.DataFrame, htf: dict[str, pd.Series]) -> dict[str, Any]:
    minute = minute.copy()
    if minute.index.tz is None:
        minute.index = minute.index.tz_localize("America/New_York")
    else:
        minute.index = minute.index.tz_convert("America/New_York")
    minute.columns = [str(column).lower() for column in minute.columns]
    rows = _read_json(FLIP_PATH, [])
    closed = [row for row in rows if isinstance(row, dict) and row.get("status") == "closed"]
    eligible = [row for row in closed if 1 <= int(row.get("contracts") or 0) <= 5]
    evidence = []
    quarantined = 0
    for row in eligible:
        view = canon.normalize_flip_trade(row)
        if view["direction"] == canon.UNKNOWN:
            # No silent right->bear default; ambiguous records are excluded
            # from alignment evidence and counted instead.
            quarantined += 1
            continue
        direction = "bull" if view["direction"] == "bullish" else "bear"
        day = str(row.get("entry_date") or row.get("entry_at") or "")[:10]
        states = asof_states(htf, day)
        pnl = float(row.get("pnl") or 0.0)
        entry_time = _entry_time(row)
        reconstructed_ltf = None
        if day and entry_time:
            checkpoint = pd.Timestamp(f"{day} {entry_time}", tz="America/New_York")
            session = minute[minute.index.date == checkpoint.date()]
            reconstructed_ltf = ltf_signal(session[session.index < checkpoint])
        evidence.append({
            "id": row.get("id"),
            "date": day,
            "entry_time_et": entry_time,
            "right": row.get("right"),
            "direction": direction,
            "pnl_dollars": pnl,
            "winner": pnl > 0,
            "strategy": row.get("strategy"),
            "catalyst": row.get("catalyst"),
            "states": states,
            "daily_aligned": direction_matches(states["daily"], direction),
            "weekly_aligned": direction_matches(states["weekly"], direction),
            "all_three_aligned": all(direction_matches(states[key], direction) for key in states),
            "telemetry": (row.get("entry_quality") or {}).get("feature_snapshot"),
            "reconstructed_ltf": reconstructed_ltf,
            "reconstructed_ltf_agrees": (
                reconstructed_ltf is not None and reconstructed_ltf["direction"] == direction
            ),
        })
    winners = [row for row in evidence if row["winner"]]
    losers = [row for row in evidence if not row["winner"]]
    return {
        "source_closed_count": len(closed),
        "current_contract_cap_count": len(evidence),
        "direction_quarantined_count": quarantined,
        "excluded_pre_hardening_count": len(closed) - len(eligible),
        "winner_count": len(winners),
        "loser_count": len(losers),
        "win_rate": round(len(winners) / len(evidence), 4) if evidence else 0.0,
        "net_pnl_dollars": round(sum(row["pnl_dollars"] for row in evidence), 2),
        "alignment_contrast": {
            key: {
                "wins": sum(row["winner"] for row in evidence if row[key]),
                "losses": sum(not row["winner"] for row in evidence if row[key]),
                "count": sum(bool(row[key]) for row in evidence),
            }
            for key in ("daily_aligned", "weekly_aligned", "all_three_aligned")
        },
        "trades": evidence,
    }


def _option_outcome(reason: Any) -> str:
    text = str(reason or "").lower()
    if "profit target" in text or "near-target" in text:
        return "win"
    if "profit protect" in text:
        match = re.search(r"([+-]?\d+(?:\.\d+)?)%", text)
        return "win" if match and float(match.group(1)) > 0 else "loss"
    if "stop loss" in text:
        return "loss"
    return "unknown"


def actual_options_reconstruction(htf_by_symbol: dict[str, dict[str, pd.Series]]) -> dict[str, Any]:
    payload = _read_json(OPTIONS_PATH, {})
    source = payload.get("trades", []) if isinstance(payload, dict) else []
    rows = [row for row in dedupe_options_trade_records(source) if row.get("status") == "closed"]
    evidence = []
    for row in rows:
        symbol = str(row.get("underlying") or "")
        outcome = _option_outcome(row.get("closing_reason"))
        opened = str(row.get("opened_at") or "")[:10]
        states = asof_states(htf_by_symbol[symbol], opened) if symbol in htf_by_symbol and opened else {
            "daily": "unavailable", "weekly": "unavailable", "monthly": "unavailable"
        }
        view = canon.normalize_options_trade(row)
        direction = view["direction"]  # structure-based: bullish/bearish/neutral/unknown
        evidence.append({
            "id": row.get("id"),
            "date": opened,
            "symbol": symbol,
            "strategy": row.get("strategy"),
            "outcome_label": outcome,
            "closing_reason": row.get("closing_reason"),
            "states": states,
            "canonical_direction": direction,
            "direction_quarantined": view["quarantined"],
            "daily_aligned": direction in ("bullish", "bearish") and states["daily"] == direction,
            "weekly_aligned": direction in ("bullish", "bearish") and states["weekly"] == direction,
            "pnl_policy": "outcome_label_only_no_fill_pnl_inference",
        })
    known = [row for row in evidence if row["outcome_label"] != "unknown"]
    return {
        "deduplicated_closed_count": len(rows),
        "known_outcome_count": len(known),
        "wins": sum(row["outcome_label"] == "win" for row in known),
        "losses": sum(row["outcome_label"] == "loss" for row in known),
        "warning": "Most records lack fill-derived realized P&L; labels are not dollar returns.",
        "trades": evidence,
    }


def shadow_overlay(htf_by_symbol: dict[str, dict[str, pd.Series]]) -> dict[str, Any]:
    episodes = _shadow_trades(SHADOW_PATH)
    completed = [episode for episode in episodes if episode.get("status") in {"winner", "loser"}]
    rows = []
    unavailable = 0
    for episode in completed:
        symbol = str(episode.get("symbol") or "")
        day = str(episode.get("date") or "")[:10]
        table = htf_by_symbol.get(symbol)
        if table is None:
            unavailable += 1
            continue
        states = asof_states(table, day)
        direction = "bull" if str(episode.get("right")).upper() == "CALL" else "bear"
        for variant in VARIANTS:
            if variant_allows(variant, states, direction):
                rows.append({
                    "date": day,
                    "symbol": symbol,
                    "right": episode.get("right"),
                    "variant": variant,
                    "return_pct": float(episode.get("evidence_exit_return_pct") or 0.0),
                    "states": states,
                })
    summaries = {}
    for variant in VARIANTS:
        selected = [row for row in rows if row["variant"] == variant]
        daily: dict[str, list[float]] = defaultdict(list)
        for row in selected:
            daily[row["date"]].append(row["return_pct"])
        clustered = [{"date": day, "return_pct": sum(values) / len(values)} for day, values in sorted(daily.items())]
        summaries[variant] = {
            "episode_metrics_pct": metrics(selected, "return_pct"),
            "date_clustered_metrics_pct": metrics(clustered, "return_pct"),
            "trading_days": len(clustered),
        }
    return {
        "source_lifecycle_count": len(episodes),
        "completed_outcome_count": len(completed),
        "episodes_without_daily_cache": unavailable,
        "summaries": summaries,
        "warning": "Shadow symbols on one date are correlated; date-clustered metrics are the primary view.",
    }


def run(completeness: str = "full_1345") -> dict[str, Any]:
    minute = pd.read_parquet(MINUTE_PATH)
    spy_daily = load_daily("SPY")
    if spy_daily is None:
        raise FileNotFoundError("SPY daily cache missing")
    htf_by_symbol = {}
    for path in DAILY_DIR.glob("*.parquet"):
        symbol = path.name.split("_", 1)[0].upper()
        frame = load_daily(symbol)
        if frame is not None:
            htf_by_symbol[symbol] = build_htf_table(frame)
    spy_htf = htf_by_symbol["SPY"]
    replay_rows, coverage = replay_spy(minute, spy_htf, completeness=completeness)
    return {
        "schema_version": 2,
        "generated_at": datetime.now().astimezone().isoformat(),
        "mode": "read_only_preregistered_reconstruction",
        "execution_enabled": False,
        "can_submit_orders": False,
        "data_warnings": [
            "SPY minute history is Alpaca IEX, not full-market SIP.",
            "Underlying returns do not reproduce 0DTE option convexity or spreads.",
            "The project has already examined the 2025+ period; it is diagnostic, not pristine OOS.",
            "Historical membership is not modeled in the daily cache universe.",
            "Complete-session filters exclude holiday half-days by construction.",
            "Completeness filters skew the sample toward high-activity sessions; "
            "expectancies are conditional on session data completeness.",
        ],
        "actual_flip": actual_flip_reconstruction(minute, spy_htf),
        "actual_options": actual_options_reconstruction(htf_by_symbol),
        "spy_replay": {
            "coverage": coverage,
            "signal_variant_rows": len(replay_rows),
            "summaries": summarize_replay(replay_rows),
        },
        "shadow_htf_overlay": shadow_overlay(htf_by_symbol),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--completeness",
        choices=("full_1345", "per_checkpoint"),
        default="full_1345",
    )
    args = parser.parse_args()
    if args.output is None:
        args.output = (
            OUTPUT_PATH
            if args.completeness == "full_1345"
            else OUTPUT_PATH.with_name("green_day_htf_ltf_results_per_checkpoint.json")
        )
    result = run(completeness=args.completeness)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "flip": {key: result["actual_flip"][key] for key in ("current_contract_cap_count", "winner_count", "net_pnl_dollars")},
        "spy_coverage": result["spy_replay"]["coverage"],
        "shadow_lifecycles": result["shadow_htf_overlay"]["source_lifecycle_count"],
        "shadow_completed": result["shadow_htf_overlay"]["completed_outcome_count"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
