#!/usr/bin/env python3
"""Evaluate EMA-and-level shadow signals against directional control days.

Read-only. The report measures underlying returns from each scanner observation
to the regular-session close. It never estimates option P&L and cannot trade.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean, median, stdev
from typing import Any, Callable
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
VIBE_HOME = Path.home() / ".vibe-trading"
SOURCE_LOG = ROOT / "data" / "premarket_ema_retest_shadow_log.jsonl"
REPORT_PATH = VIBE_HOME / "reports" / "premarket-ema-retest-outcomes.json"
EVALUATION_LOG = ROOT / "data" / "premarket_ema_retest_outcome_log.jsonl"
NY = ZoneInfo("America/New_York")
ROUND_TRIP_COST_BPS = 2.0
OOS_FRACTION = 0.20
MIN_TRADING_DAYS = 30
MIN_SIGNAL_OUTCOMES = 10
MIN_CONTROL_OUTCOMES = 10
MIN_OOS_SIGNALS = 5


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=NY)
    return parsed.astimezone(NY)


def _corrected_rule_classification(scan: dict[str, Any]) -> tuple[str, str | None, int]:
    features = scan.get("features") if isinstance(scan.get("features"), dict) else {}
    bull_score = int(_number(scan.get("bull_score")) or 0)
    bear_score = int(_number(scan.get("bear_score")) or 0)
    bull_stack = bool(features.get("bull_stack_13_48_200"))
    bear_stack = bool(features.get("bear_stack_13_48_200"))
    if bull_score >= 7 and bull_stack:
        return "signal", "call", bull_score
    if bear_score >= 7 and bear_stack:
        return "signal", "put", bear_score
    if bull_score > bear_score:
        return "control", "call", bull_score
    if bear_score > bull_score:
        return "control", "put", bear_score
    return "neutral_control", None, max(bull_score, bear_score)


def _observation_time(report: dict[str, Any], scan: dict[str, Any]) -> datetime | None:
    explicit = _parse_time(scan.get("as_of"))
    if explicit is not None:
        return explicit
    generated = _parse_time(report.get("timestamp"))
    report_date = str(report.get("date") or "")[:10]
    if generated is None or generated.date().isoformat() != report_date:
        return None
    return generated


def _normalize_bars(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    bars = frame.copy()
    bars.columns = [str(column).lower() for column in bars.columns]
    bars.index = pd.to_datetime(bars.index)
    if bars.index.tz is None:
        bars.index = bars.index.tz_localize(NY)
    else:
        bars.index = bars.index.tz_convert(NY)
    return bars.sort_index()


def evaluate_observation(
    report: dict[str, Any],
    scan: dict[str, Any],
    bars: pd.DataFrame,
    *,
    round_trip_cost_bps: float = ROUND_TRIP_COST_BPS,
) -> dict[str, Any] | None:
    if scan.get("status") != "ok":
        return None
    observed_at = _observation_time(report, scan)
    entry = _number(scan.get("latest_close"))
    if observed_at is None or entry is None or entry <= 0:
        return None
    cohort, direction, score = _corrected_rule_classification(scan)
    if direction is None:
        return {
            "date": str(report.get("date") or "")[:10],
            "symbol": str(scan.get("symbol") or "").upper(),
            "cohort": cohort,
            "direction": None,
            "score": score,
            "observed_at": observed_at.isoformat(),
            "status": "neutral_no_direction",
        }
    normalized = _normalize_bars(bars)
    same_day = normalized[normalized.index.date == observed_at.date()]
    forward = same_day[same_day.index > observed_at]
    if forward.empty or not {"high", "low", "close"}.issubset(forward.columns):
        return None
    exit_price = float(forward["close"].iloc[-1])
    direction_mult = 1.0 if direction == "call" else -1.0
    gross_bps = direction_mult * (exit_price - entry) / entry * 10_000
    if direction == "call":
        mfe_bps = (float(forward["high"].max()) - entry) / entry * 10_000
        mae_bps = (float(forward["low"].min()) - entry) / entry * 10_000
    else:
        mfe_bps = (entry - float(forward["low"].min())) / entry * 10_000
        mae_bps = (entry - float(forward["high"].max())) / entry * 10_000
    net_bps = gross_bps - round_trip_cost_bps
    return {
        "date": str(report.get("date") or "")[:10],
        "symbol": str(scan.get("symbol") or "").upper(),
        "cohort": cohort,
        "direction": direction,
        "score": score,
        "logged_action": scan.get("action"),
        "rule_version": "ema_level_v2_aligned_stack_required",
        "observed_at": observed_at.isoformat(),
        "entry_price": round(entry, 4),
        "exit_price": round(exit_price, 4),
        "gross_return_bps": round(gross_bps, 3),
        "modeled_cost_bps": round(round_trip_cost_bps, 3),
        "net_return_bps": round(net_bps, 3),
        "mfe_bps": round(mfe_bps, 3),
        "mae_bps": round(mae_bps, 3),
        "bar_count": len(forward),
        "status": "win" if net_bps > 0 else "loss",
        "features": scan.get("features") or {},
    }


def _dedupe_reports(reports: list[dict[str, Any]]) -> tuple[list[tuple[dict[str, Any], dict[str, Any]]], int]:
    selected: dict[tuple[str, str], tuple[dict[str, Any], dict[str, Any]]] = {}
    excluded_replays = 0
    for report in reports:
        report_date = str(report.get("date") or "")[:10]
        scans = report.get("scans") if isinstance(report.get("scans"), list) else []
        for scan in scans:
            if not isinstance(scan, dict) or scan.get("status") != "ok":
                continue
            symbol = str(scan.get("symbol") or "").upper()
            observed_at = _observation_time(report, scan)
            if not report_date or not symbol or observed_at is None:
                excluded_replays += 1
                continue
            key = (report_date, symbol)
            current = selected.get(key)
            if current is None or observed_at < (_observation_time(*current) or observed_at):
                selected[key] = (report, scan)
    ordered = sorted(selected.values(), key=lambda item: (str(item[0].get("date")), str(item[1].get("symbol"))))
    return ordered, excluded_replays


def _mean_ci(values: list[float]) -> list[float] | None:
    if len(values) < 5:
        return None
    margin = 1.96 * stdev(values) / math.sqrt(len(values))
    center = fmean(values)
    return [round(center - margin, 3), round(center + margin, 3)]


def _max_drawdown(values: list[float]) -> float | None:
    if not values:
        return None
    equity = peak = 0.0
    worst = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return round(worst, 3)


def summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [item for item in items if item.get("status") in {"win", "loss"}]
    values = [float(item["net_return_bps"]) for item in closed]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value <= 0]
    return {
        "count": len(closed),
        "trading_day_count": len({item["date"] for item in closed}),
        "win_rate": round(len(wins) / len(values), 4) if values else None,
        "expectancy_net_bps": round(fmean(values), 3) if values else None,
        "expectancy_95_ci_bps": _mean_ci(values),
        "median_net_bps": round(median(values), 3) if values else None,
        "average_win_bps": round(fmean(wins), 3) if wins else None,
        "average_loss_bps": round(fmean(losses), 3) if losses else None,
        "profit_factor": round(sum(wins) / abs(sum(losses)), 3) if losses and sum(losses) != 0 else None,
        "max_drawdown_bps": _max_drawdown(values),
        "average_mfe_bps": round(fmean(float(item["mfe_bps"]) for item in closed), 3) if closed else None,
        "average_mae_bps": round(fmean(float(item["mae_bps"]) for item in closed), 3) if closed else None,
    }


def _holdout(items: list[dict[str, Any]], fraction: float = OOS_FRACTION) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ordered = sorted(items, key=lambda item: (item["date"], item["symbol"]))
    if len(ordered) < 2:
        return ordered, []
    holdout_count = max(1, math.ceil(len(ordered) * fraction))
    return ordered[:-holdout_count], ordered[-holdout_count:]


def _fetch_bars(symbol: str, trading_day: str) -> pd.DataFrame:
    from scripts.premarket_ema_retest_shadow_logger import fetch_intraday_bars_alpaca

    return fetch_intraday_bars_alpaca(symbol, datetime.fromisoformat(trading_day).date())


def build_report(
    source_log: Path = SOURCE_LOG,
    *,
    fetcher: Callable[[str, str], pd.DataFrame] = _fetch_bars,
    round_trip_cost_bps: float = ROUND_TRIP_COST_BPS,
) -> dict[str, Any]:
    reports = _read_jsonl(source_log)
    observations, excluded_replays = _dedupe_reports(reports)
    episodes: list[dict[str, Any]] = []
    fetch_errors: list[dict[str, str]] = []
    cache: dict[tuple[str, str], pd.DataFrame] = {}
    for report, scan in observations:
        symbol = str(scan.get("symbol") or "").upper()
        trading_day = str(report.get("date") or "")[:10]
        key = (symbol, trading_day)
        try:
            if key not in cache:
                cache[key] = fetcher(symbol, trading_day)
            episode = evaluate_observation(
                report,
                scan,
                cache[key],
                round_trip_cost_bps=round_trip_cost_bps,
            )
        except Exception as exc:
            fetch_errors.append({"symbol": symbol, "date": trading_day, "error": str(exc)[:180]})
            continue
        if episode is not None:
            episodes.append(episode)

    directional = [item for item in episodes if item.get("status") in {"win", "loss"}]
    signals = [item for item in directional if item["cohort"] == "signal"]
    controls = [item for item in directional if item["cohort"] == "control"]
    train, oos = _holdout(signals)
    signal_summary = summarize(signals)
    control_summary = summarize(controls)
    train_summary = summarize(train)
    oos_summary = summarize(oos)
    signal_expectancy = _number(signal_summary.get("expectancy_net_bps"))
    control_expectancy = _number(control_summary.get("expectancy_net_bps"))
    lift = (
        signal_expectancy - control_expectancy
        if signal_expectancy is not None and control_expectancy is not None
        else None
    )
    days = len({item["date"] for item in directional})
    blockers: list[str] = []
    if days < MIN_TRADING_DAYS:
        blockers.append("fewer_than_30_trading_days")
    if len(signals) < MIN_SIGNAL_OUTCOMES:
        blockers.append("fewer_than_10_signal_outcomes")
    if len(controls) < MIN_CONTROL_OUTCOMES:
        blockers.append("fewer_than_10_directional_controls")
    if len(oos) < MIN_OOS_SIGNALS:
        blockers.append("fewer_than_5_chronological_holdout_signals")
    if signal_expectancy is None or signal_expectancy <= 0:
        blockers.append("signal_expectancy_not_positive")
    signal_ci = signal_summary.get("expectancy_95_ci_bps")
    if not isinstance(signal_ci, list) or not signal_ci or float(signal_ci[0]) <= 0:
        blockers.append("signal_expectancy_confidence_interval_not_above_zero")
    if _number(oos_summary.get("expectancy_net_bps")) is None or float(oos_summary["expectancy_net_bps"]) <= 0:
        blockers.append("holdout_expectancy_not_positive")
    if lift is None or lift <= 0:
        blockers.append("positive_lift_over_directional_controls_not_proven")

    confidence = min(4.0, len(signals) / MIN_SIGNAL_OUTCOMES * 4.0)
    confidence += min(2.0, days / MIN_TRADING_DAYS * 2.0)
    confidence += min(1.0, len(controls) / MIN_CONTROL_OUTCOMES)
    confidence += min(1.0, len(oos) / MIN_OOS_SIGNALS)
    confidence += 1.0 if signal_expectancy is not None and signal_expectancy > 0 else 0.0
    confidence += 1.0 if lift is not None and lift > 0 else 0.0

    profitability_confidence = min(2.0, len(signals) / MIN_SIGNAL_OUTCOMES * 2.0)
    profitability_confidence += min(1.0, days / MIN_TRADING_DAYS)
    profitability_confidence += min(1.0, len(controls) / MIN_CONTROL_OUTCOMES)
    profitability_confidence += 1.0 if signal_expectancy is not None and signal_expectancy > 0 else 0.0
    profitability_confidence += 2.0 if isinstance(signal_ci, list) and signal_ci and float(signal_ci[0]) > 0 else 0.0
    profitability_confidence += 2.0 if _number(oos_summary.get("expectancy_net_bps")) is not None and float(oos_summary["expectancy_net_bps"]) > 0 else 0.0
    profitability_confidence += 1.0 if lift is not None and lift > 0 else 0.0

    by_symbol: dict[str, dict[str, Any]] = {}
    for symbol in sorted({item["symbol"] for item in directional}):
        symbol_items = [item for item in directional if item["symbol"] == symbol]
        by_symbol[symbol] = {
            "signal": summarize([item for item in symbol_items if item["cohort"] == "signal"]),
            "control": summarize([item for item in symbol_items if item["cohort"] == "control"]),
        }

    return {
        "schema_version": 1,
        "provider": "premarket_ema_retest_outcome_report",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "mode": "read_only_underlying_outcome_research",
        "execution_enabled": False,
        "can_submit_orders": False,
        "source_path": str(source_log),
        "outcome_model": {
            "entry": "scanner latest_close at observation time",
            "exit": "same-day regular-session final minute close",
            "return_unit": "underlying basis points, not option P&L",
            "round_trip_cost_bps": round(round_trip_cost_bps, 3),
            "corrected_rule": "score >= 7 and matching 13/48/200 EMA stack",
            "control": "observation failing the corrected signal gate, directed by the larger bull/bear score",
            "chronological_holdout_fraction": OOS_FRACTION,
        },
        "source_report_count": len(reports),
        "deduplicated_observation_count": len(observations),
        "excluded_replay_or_unusable_count": excluded_replays,
        "fetch_error_count": len(fetch_errors),
        "fetch_errors": fetch_errors,
        "directional_episode_count": len(directional),
        "trading_day_count": days,
        "neutral_control_count": sum(item.get("cohort") == "neutral_control" for item in episodes),
        "signal": signal_summary,
        "control": control_summary,
        "train": train_summary,
        "chronological_holdout": oos_summary,
        "signal_vs_control_expectancy_lift_bps": round(lift, 3) if lift is not None else None,
        "by_symbol": by_symbol,
        "evidence_confidence_score": round(min(10.0, confidence), 2),
        "profitability_confidence_score": round(min(10.0, profitability_confidence), 2),
        "review_eligible": not blockers,
        "promotion_blockers": blockers,
        "episodes": directional,
        "warnings": [
            "Underlying returns cannot be interpreted as option-contract returns.",
            "Controls are directional score controls, not randomized counterfactuals.",
            "Confidence measures evidence completeness, not probability of future profit.",
            "This report cannot change thresholds, promote a strategy, or submit orders.",
        ],
    }


def write_report(report: dict[str, Any], path: Path = REPORT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def append_log(report: dict[str, Any], path: Path = EVALUATION_LOG) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")


def print_report(report: dict[str, Any]) -> None:
    signal = report["signal"]
    control = report["control"]
    print("\nPremarket EMA Retest Outcomes | read-only underlying research")
    print("=" * 78)
    print(
        f"signals={signal['count']} controls={control['count']} "
        f"days={report['trading_day_count']} "
        f"evidence={report['evidence_confidence_score']}/10 "
        f"profitability={report['profitability_confidence_score']}/10"
    )
    print(
        f"signal expectancy={signal['expectancy_net_bps']} bps "
        f"win_rate={signal['win_rate']} max_dd={signal['max_drawdown_bps']} bps"
    )
    print(
        f"control expectancy={control['expectancy_net_bps']} bps "
        f"lift={report['signal_vs_control_expectancy_lift_bps']} bps"
    )
    print(f"review_eligible={report['review_eligible']} blockers={','.join(report['promotion_blockers'])}")
    print("No orders placed.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-log", type=Path, default=SOURCE_LOG)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--evaluation-log", type=Path, default=EVALUATION_LOG)
    parser.add_argument("--round-trip-cost-bps", type=float, default=ROUND_TRIP_COST_BPS)
    parser.add_argument("--print", action="store_true", dest="do_print")
    parser.add_argument("--no-append", action="store_true")
    args = parser.parse_args()
    report = build_report(args.source_log, round_trip_cost_bps=args.round_trip_cost_bps)
    write_report(report, args.report_path)
    if not args.no_append:
        append_log(report, args.evaluation_log)
    if args.do_print:
        print_report(report)
    else:
        print(f"Premarket EMA retest outcome report wrote {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
