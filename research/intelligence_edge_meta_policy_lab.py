#!/usr/bin/env python3
"""Frozen causal MES intelligence meta-policy replay.

The specification is preregistered in
`INTELLIGENCE_EDGE_META_POLICY_PREREGISTRATION_2026-08-17.md`. Historical
results are discovery evidence only because the available dates were consumed
by earlier research. This module cannot submit orders or change bot settings.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.topstep_prop_bot import (
    Candle,
    OpeningRangeConfig,
    PropSignal,
    assess_futures_signal_intelligence,
    build_delta_fingerprint_signal,
    build_false_breakout_signal,
    build_first_pullback_signal,
    build_opening_range_signal,
    build_vwap_deviation_signal,
    contract_for_symbol,
    load_candles_csv,
)


DEFAULT_CSV = ROOT / "examples" / "mes_v0_1m_2022-01-01_2026-07-19_rth.csv"
DEFAULT_OUTPUT = ROOT / "data" / "intelligence_edge_meta_policy_results.json"
SPEC_PATH = ROOT / "research" / "INTELLIGENCE_EDGE_META_POLICY_PREREGISTRATION_2026-08-17.md"
OR_CONFIG = OpeningRangeConfig(range_minutes=15, min_breakout_points=2.0, reward_risk=1.5)
BASELINE_SLIPPAGE_TICKS = 1
STRESS_SLIPPAGE_TICKS = 2
COMMISSION_PER_RT = 4.0
BOOTSTRAP_SEED = 20260817
BOOTSTRAP_SAMPLES = 5000
BOOTSTRAP_BLOCK_DAYS = 5


@dataclass(frozen=True)
class Candidate:
    signal: PropSignal
    entry_index: int
    intelligence: dict[str, Any]


@dataclass(frozen=True)
class ReplayTrade:
    date: str
    strategy: str
    side: str
    entry_time: str
    exit_time: str
    exit_reason: str
    intelligence_score: float
    baseline_pnl: float
    stress_pnl: float


def _group_by_date(candles: list[Candle]) -> dict[str, list[Candle]]:
    grouped: dict[str, list[Candle]] = defaultdict(list)
    for candle in candles:
        grouped[candle.timestamp.date().isoformat()].append(candle)
    return dict(grouped)


def _candidate_signals(candles: list[Candle], symbol: str) -> list[tuple[PropSignal, int]]:
    rows: list[tuple[PropSignal, int]] = []
    opening = build_opening_range_signal(candles, OR_CONFIG, symbol=symbol)
    if opening is not None:
        rows.append((opening, OR_CONFIG.range_minutes))
    pullback = build_first_pullback_signal(
        candles,
        OR_CONFIG,
        symbol=symbol,
        pullback_tolerance_ticks=4,
        pullback_stop_ticks=8,
        require_bos_confirm=True,
    )
    if pullback is not None:
        rows.append(pullback)
    false_breakout = build_false_breakout_signal(candles, OR_CONFIG, symbol=symbol)
    if false_breakout is not None:
        rows.append(false_breakout)
    vwap_deviation = build_vwap_deviation_signal(
        candles,
        OR_CONFIG,
        symbol=symbol,
        deviation_points=4.0,
    )
    if vwap_deviation is not None:
        rows.append(vwap_deviation)
    delta = build_delta_fingerprint_signal(
        candles,
        OR_CONFIG,
        symbol=symbol,
        delta_threshold=0.20,
    )
    if delta is not None:
        rows.append(delta)
    return rows


def passes_frozen_intelligence_filter(assessment: dict[str, Any]) -> bool:
    return bool(
        assessment.get("regime_compatible") is True
        and float(assessment.get("data_completeness") or 0.0) >= 0.65
        and int(assessment.get("independent_support_families") or 0) >= 2
        and float(assessment.get("support_ratio") or 0.0) >= 0.60
        and float(assessment.get("conflict_ratio") or 1.0) <= 0.35
        and float(assessment.get("reward_risk") or 0.0) >= 1.0
        and assessment.get("execution_economics_ok") is True
        and float(assessment.get("friction_to_reward") or 1.0) <= 0.35
    )


def select_candidate(candles: list[Candle], symbol: str = "MES") -> tuple[Candidate | None, dict[str, int]]:
    diagnostics = Counter()
    candidates: list[Candidate] = []
    for signal, entry_index in _candidate_signals(candles, symbol):
        diagnostics[f"generated_{signal.strategy}"] += 1
        assessment = assess_futures_signal_intelligence(
            signal,
            candles,
            entry_index=entry_index,
            round_trip_commission=COMMISSION_PER_RT,
            forward_validated_edge=False,
        )
        if not passes_frozen_intelligence_filter(assessment):
            diagnostics[f"rejected_{signal.strategy}"] += 1
            continue
        candidates.append(Candidate(signal, entry_index, assessment))
    if not candidates:
        diagnostics["no_qualifying_candidate"] += 1
        return None, dict(diagnostics)
    candidates.sort(
        key=lambda row: (
            row.entry_index,
            -float(row.intelligence.get("intelligence_score") or 0.0),
            row.signal.strategy,
        )
    )
    selected = candidates[0]
    diagnostics[f"selected_{selected.signal.strategy}"] += 1
    diagnostics["qualified_candidates"] += len(candidates)
    return selected, dict(diagnostics)


def _exit_level(
    candles: list[Candle],
    *,
    side: str,
    stop: float,
    target: float,
    fallback: Candle,
) -> tuple[float, datetime, str]:
    for candle in candles:
        if side == "buy":
            if candle.low <= stop:
                return stop, candle.timestamp, "stop"
            if candle.high >= target:
                return target, candle.timestamp, "target"
        else:
            if candle.high >= stop:
                return stop, candle.timestamp, "stop"
            if candle.low <= target:
                return target, candle.timestamp, "target"
    last = candles[-1] if candles else fallback
    return last.close, last.timestamp, "eod"


def _pnl_with_costs(
    candidate: Candidate,
    candles: list[Candle],
    *,
    slippage_ticks: int,
    commission: float,
    symbol: str,
) -> tuple[float, str, str]:
    signal = candidate.signal
    contract = contract_for_symbol(symbol)
    slippage = slippage_ticks * contract.tick_size
    entry = signal.entry + slippage if signal.side == "buy" else signal.entry - slippage
    raw_exit, exit_time, reason = _exit_level(
        candles[candidate.entry_index + 1 :],
        side=signal.side,
        stop=signal.stop,
        target=signal.target,
        fallback=candles[candidate.entry_index],
    )
    exit_price = raw_exit - slippage if signal.side == "buy" else raw_exit + slippage
    points = exit_price - entry if signal.side == "buy" else entry - exit_price
    return round(points * contract.point_value - commission, 2), exit_time.isoformat(), reason


def replay_session(candles: list[Candle], symbol: str = "MES") -> tuple[ReplayTrade | None, dict[str, int]]:
    selected, diagnostics = select_candidate(candles, symbol)
    if selected is None:
        return None, diagnostics
    baseline, exit_time, reason = _pnl_with_costs(
        selected,
        candles,
        slippage_ticks=BASELINE_SLIPPAGE_TICKS,
        commission=COMMISSION_PER_RT,
        symbol=symbol,
    )
    stress, _, _ = _pnl_with_costs(
        selected,
        candles,
        slippage_ticks=STRESS_SLIPPAGE_TICKS,
        commission=COMMISSION_PER_RT,
        symbol=symbol,
    )
    signal = selected.signal
    return ReplayTrade(
        date=candles[selected.entry_index].timestamp.date().isoformat(),
        strategy=signal.strategy,
        side=signal.side,
        entry_time=candles[selected.entry_index].timestamp.isoformat(),
        exit_time=exit_time,
        exit_reason=reason,
        intelligence_score=float(selected.intelligence.get("intelligence_score") or 0.0),
        baseline_pnl=baseline,
        stress_pnl=stress,
    ), diagnostics


def _max_drawdown(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = min(drawdown, equity - peak)
    return round(drawdown, 2)


def _bootstrap_lower(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    rng = random.Random(BOOTSTRAP_SEED)
    means: list[float] = []
    n = len(values)
    block = min(BOOTSTRAP_BLOCK_DAYS, n)
    for _ in range(BOOTSTRAP_SAMPLES):
        sample: list[float] = []
        while len(sample) < n:
            start = rng.randrange(n)
            sample.extend(values[(start + offset) % n] for offset in range(block))
        means.append(statistics.fmean(sample[:n]))
    means.sort()
    return round(means[int(0.025 * (len(means) - 1))], 4)


def metrics(trades: list[ReplayTrade], field: str = "baseline_pnl") -> dict[str, Any]:
    values = [float(getattr(trade, field)) for trade in trades]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value <= 0]
    gross_loss = abs(sum(losses))
    remove_count = math.ceil(len(values) * 0.05) if values else 0
    trimmed = sorted(values, reverse=True)[remove_count:]
    return {
        "trades": len(values),
        "independent_sessions": len({trade.date for trade in trades}),
        "total_pnl": round(sum(values), 2),
        "expectancy": round(statistics.fmean(values), 4) if values else 0.0,
        "win_rate": round(len(wins) / len(values), 4) if values else 0.0,
        "profit_factor": round(sum(wins) / gross_loss, 4) if gross_loss else (999.0 if wins else 0.0),
        "max_drawdown": _max_drawdown(values),
        "top5_removed_expectancy": round(statistics.fmean(trimmed), 4) if trimmed else 0.0,
        "bootstrap_95_lower_mean": _bootstrap_lower(values),
    }


def _segment(trades: list[ReplayTrade], name: str) -> list[ReplayTrade]:
    if name == "development":
        return [trade for trade in trades if trade.date <= "2024-12-31"]
    if name == "confirmation":
        return [trade for trade in trades if "2025-01-01" <= trade.date <= "2025-12-31"]
    if name == "recent":
        return [trade for trade in trades if trade.date >= "2026-01-01"]
    return trades


def build_report(candles: list[Candle], symbol: str = "MES") -> dict[str, Any]:
    grouped = _group_by_date(candles)
    trades: list[ReplayTrade] = []
    diagnostics = Counter()
    for session_date in sorted(grouped):
        trade, day_diagnostics = replay_session(grouped[session_date], symbol)
        diagnostics.update(day_diagnostics)
        if trade is not None:
            trades.append(trade)
    segments = {
        name: {
            "baseline": metrics(_segment(trades, name), "baseline_pnl"),
            "stress": metrics(_segment(trades, name), "stress_pnl"),
        }
        for name in ("development", "confirmation", "recent", "full")
    }
    full = segments["full"]["baseline"]
    stress = segments["full"]["stress"]
    checks = {
        "minimum_100_trades": full["trades"] >= 100,
        "minimum_100_sessions": full["independent_sessions"] >= 100,
        "profit_factor_at_least_1_20": full["profit_factor"] >= 1.20,
        "baseline_expectancy_positive": full["expectancy"] > 0,
        "stress_expectancy_positive": stress["expectancy"] > 0,
        "confirmation_expectancy_positive": segments["confirmation"]["baseline"]["expectancy"] > 0,
        "recent_expectancy_positive": segments["recent"]["baseline"]["expectancy"] > 0,
        "max_drawdown_within_500": full["max_drawdown"] >= -500.0,
        "top5_removed_expectancy_positive": full["top5_removed_expectancy"] > 0,
        "bootstrap_lower_bound_positive": (
            full["bootstrap_95_lower_mean"] is not None
            and full["bootstrap_95_lower_mean"] > 0
        ),
    }
    passed = all(checks.values())
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "specification": str(SPEC_PATH),
        "specification_sha256": hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest(),
        "symbol": symbol,
        "sessions_available": len(grouped),
        "date_range": [min(grouped), max(grouped)] if grouped else [],
        "parameters": {
            "opening_range": asdict(OR_CONFIG),
            "baseline_slippage_ticks_each_side": BASELINE_SLIPPAGE_TICKS,
            "stress_slippage_ticks_each_side": STRESS_SLIPPAGE_TICKS,
            "commission_per_rt": COMMISSION_PER_RT,
            "maximum_trades_per_session": 1,
        },
        "candidate_diagnostics": dict(sorted(diagnostics.items())),
        "strategy_counts": dict(Counter(trade.strategy for trade in trades)),
        "segments": segments,
        "review_gate": {
            "passed": passed,
            "checks": checks,
            "verdict": "forward_candidate" if passed else "rejected_historical_candidate",
        },
        "trades": [asdict(trade) for trade in trades],
        "historical_data_consumed": True,
        "practice_eligible": False,
        "execution_enabled": False,
        "can_submit_orders": False,
        "authority": "research_only",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--symbol", default="MES")
    args = parser.parse_args()
    report = build_report(load_candles_csv(args.csv), args.symbol)
    report["source_data"] = str(args.csv)
    report["source_data_sha256"] = hashlib.sha256(args.csv.read_bytes()).hexdigest()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "sessions_available", "date_range", "strategy_counts", "segments", "review_gate",
        "practice_eligible", "can_submit_orders",
    )}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
