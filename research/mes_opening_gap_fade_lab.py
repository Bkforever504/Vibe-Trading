#!/usr/bin/env python3
"""Research-only MES opening-gap failure/fade diagnostic."""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass
from datetime import time
from pathlib import Path
from statistics import NormalDist
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.topstep_combine_simulator import CombineRules, bootstrap_combine


DEFAULT_CSV = ROOT / "examples" / "mes_v0_1m_2022-01-01_2026-07-19_rth.csv"
DEFAULT_OUT = ROOT / "data" / "mes_opening_gap_fade_results.json"
PREREGISTRATION = "research/MES_OPENING_GAP_FADE_PREREGISTRATION_2026-08-09.md"

TICK = 0.25
POINT_VALUE = 5.0
COMMISSION_PER_SIDE = 1.24
SLIPPAGE_TICKS_PER_SIDE = 1
FAMILY_ATTEMPTS = 12
FAMILYWISE_ALPHA = 0.05 / FAMILY_ATTEMPTS
RTH_OPEN = time(9, 30)
COMPLETE_THROUGH = time(15, 55)
FLATTEN_TIME = time(12, 0)


@dataclass(frozen=True)
class GapFadeConfig:
    min_gap_pct: float
    confirmation_minutes: int
    rejection_fraction: float
    min_reward_risk: float = 1.25
    stop_buffer_ticks: int = 2
    max_risk_ticks: int = 60

    @property
    def name(self) -> str:
        gap = str(self.min_gap_pct).replace(".", "p")
        rejection = str(self.rejection_fraction).replace(".", "p")
        return f"gap{gap}_confirm{self.confirmation_minutes}_reject{rejection}"


@dataclass(frozen=True)
class GapSession:
    day: str
    bars: pd.DataFrame
    prior_close: float
    gap_pct: float


@dataclass(frozen=True)
class GapTrade:
    day: str
    side: str
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    stop_price: float
    target_price: float
    raw_points: float
    exit_reason: str


def parameter_grid() -> list[GapFadeConfig]:
    return [
        GapFadeConfig(gap, confirmation, rejection)
        for gap in (0.35, 0.50, 0.75)
        for confirmation in (5, 15)
        for rejection in (0.25, 0.50)
    ]


def prepare_sessions(frame: pd.DataFrame, *, start_date: str = "2024-01-01") -> tuple[list[str], dict[str, GapSession], dict[str, int]]:
    required = {"timestamp", "open", "high", "low", "close", "volume", "instrument_id"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"missing required columns: {', '.join(missing)}")

    work = frame.copy()
    work["dt"] = pd.to_datetime(work["timestamp"], errors="raise")
    work["date"] = work["dt"].dt.date.astype(str)
    grouped = [(day, bars.sort_values("dt").reset_index(drop=True)) for day, bars in work.groupby("date", sort=True)]

    sessions: dict[str, GapSession] = {}
    skipped = {"before_start": 0, "incomplete": 0, "no_prior": 0, "roll_boundary": 0}
    prior_bars: pd.DataFrame | None = None
    for day, bars in grouped:
        first_time = bars.iloc[0]["dt"].time()
        last_time = bars.iloc[-1]["dt"].time()
        complete = len(bars) >= 300 and first_time == RTH_OPEN and last_time >= COMPLETE_THROUGH
        prior_complete = (
            prior_bars is not None
            and len(prior_bars) >= 300
            and prior_bars.iloc[0]["dt"].time() == RTH_OPEN
            and prior_bars.iloc[-1]["dt"].time() >= COMPLETE_THROUGH
        )
        if day < start_date:
            skipped["before_start"] += 1
        elif not complete:
            skipped["incomplete"] += 1
        elif not prior_complete:
            skipped["no_prior"] += 1
        elif str(bars.iloc[0]["instrument_id"]) != str(prior_bars.iloc[-1]["instrument_id"]):
            skipped["roll_boundary"] += 1
        else:
            prior_close = float(prior_bars.iloc[-1]["close"])
            opening = float(bars.iloc[0]["open"])
            sessions[day] = GapSession(
                day=day,
                bars=bars,
                prior_close=prior_close,
                gap_pct=(opening / prior_close - 1.0) * 100.0,
            )
        prior_bars = bars
    return sorted(sessions), sessions, skipped


def simulate_session(session: GapSession, config: GapFadeConfig, *, entry_delay_bars: int = 0) -> GapTrade | None:
    bars = session.bars
    if abs(session.gap_pct) < config.min_gap_pct or len(bars) <= config.confirmation_minutes + entry_delay_bars:
        return None

    opening = float(bars.iloc[0]["open"])
    gap_points = opening - session.prior_close
    gap_direction = 1 if gap_points > 0 else -1
    confirmation = bars.iloc[: config.confirmation_minutes]
    confirmation_close = float(confirmation.iloc[-1]["close"])
    rejection_points = gap_direction * (opening - confirmation_close)
    if rejection_points < abs(gap_points) * config.rejection_fraction:
        return None

    side = -gap_direction
    entry_idx = config.confirmation_minutes + entry_delay_bars
    entry_row = bars.iloc[entry_idx]
    entry = float(entry_row["open"])
    buffer_points = config.stop_buffer_ticks * TICK
    stop = (
        float(confirmation["high"].max()) + buffer_points
        if side < 0
        else float(confirmation["low"].min()) - buffer_points
    )
    target = session.prior_close
    risk_points = side * (entry - stop)
    reward_points = side * (target - entry)
    if risk_points <= 0 or reward_points <= 0:
        return None
    risk_ticks = risk_points / TICK
    if risk_ticks < 4 or risk_ticks > config.max_risk_ticks:
        return None
    if reward_points / risk_points < config.min_reward_risk:
        return None

    exit_price = float(bars.iloc[-1]["close"])
    exit_time = bars.iloc[-1]["dt"]
    exit_reason = "eod"
    for _, row in bars.iloc[entry_idx:].iterrows():
        row_time = row["dt"].time()
        if row_time >= FLATTEN_TIME:
            exit_price = float(row["open"])
            exit_time = row["dt"]
            exit_reason = "time"
            break
        high = float(row["high"])
        low = float(row["low"])
        if side > 0:
            if low <= stop:
                exit_price, exit_time, exit_reason = stop, row["dt"], "stop"
                break
            if high >= target:
                exit_price, exit_time, exit_reason = target, row["dt"], "target"
                break
        else:
            if high >= stop:
                exit_price, exit_time, exit_reason = stop, row["dt"], "stop"
                break
            if low <= target:
                exit_price, exit_time, exit_reason = target, row["dt"], "target"
                break

    return GapTrade(
        day=session.day,
        side="buy" if side > 0 else "sell",
        entry_time=entry_row["dt"].isoformat(),
        exit_time=exit_time.isoformat(),
        entry_price=round(entry, 4),
        exit_price=round(exit_price, 4),
        stop_price=round(stop, 4),
        target_price=round(target, 4),
        raw_points=round(side * (exit_price - entry), 4),
        exit_reason=exit_reason,
    )


def trade_pnl(trade: GapTrade, *, cost_multiple: float = 1.0) -> float:
    per_side = COMMISSION_PER_SIDE + SLIPPAGE_TICKS_PER_SIDE * TICK * POINT_VALUE
    return trade.raw_points * POINT_VALUE - 2 * per_side * cost_multiple


def metrics(trades: list[GapTrade], *, cost_multiple: float = 1.0, remove_top_pct: float = 0.0) -> dict[str, Any]:
    pnls = [trade_pnl(trade, cost_multiple=cost_multiple) for trade in trades]
    if remove_top_pct and pnls:
        remove_count = max(1, math.ceil(len(pnls) * remove_top_pct))
        for index in sorted(range(len(pnls)), key=pnls.__getitem__, reverse=True)[:remove_count]:
            pnls[index] = 0.0
    if not pnls:
        return {"trades": 0, "expectancy": None, "profit_factor": None, "win_rate": None, "p_value": None}
    wins = sum(value for value in pnls if value > 0)
    losses = -sum(value for value in pnls if value <= 0)
    mean = sum(pnls) / len(pnls)
    variance = sum((value - mean) ** 2 for value in pnls) / max(1, len(pnls) - 1)
    standard_error = math.sqrt(variance / len(pnls)) if variance > 0 else 0.0
    t_stat = mean / standard_error if standard_error else (float("inf") if mean > 0 else 0.0)
    p_value = 1 - NormalDist().cdf(t_stat) if math.isfinite(t_stat) else 0.0
    equity = pd.Series([0.0, *pnls]).cumsum()
    return {
        "trades": len(pnls),
        "total_pnl": round(sum(pnls), 2),
        "expectancy": round(mean, 4),
        "win_rate": round(sum(value > 0 for value in pnls) / len(pnls), 4),
        "profit_factor": round(wins / losses, 4) if losses else None,
        "max_drawdown": round(float((equity.cummax() - equity).max()), 2),
        "t_stat": round(t_stat, 4) if math.isfinite(t_stat) else None,
        "p_value": round(p_value, 8),
    }


def _historical_stability_pass(row: dict[str, Any]) -> bool:
    minimums = {"2024": 15, "2025": 15, "2026": 8}
    for year, minimum in minimums.items():
        base = row["annual"].get(year, {})
        stress = row["annual_2x_cost"].get(year, {})
        if (
            base.get("trades", 0) < minimum
            or (base.get("expectancy") or 0) <= 0
            or (base.get("profit_factor") or 0) < 1.05
            or (stress.get("expectancy") or 0) <= 0
        ):
            return False
    p_value = row["aggregate_2x_cost"].get("p_value")
    return (
        (row["aggregate_2x_cost"].get("profit_factor") or 0) >= 1.10
        and p_value is not None
        and p_value <= FAMILYWISE_ALPHA
        and (row["aggregate_2x_cost_one_bar_delay"].get("expectancy") or 0) > 0
        and (row["aggregate_2x_cost_without_top_1pct"].get("expectancy") or 0) > 0
    )


def _candidate_rank(row: dict[str, Any]) -> tuple[Any, ...]:
    required_years = ("2024", "2025", "2026")
    annual_rows = [row["annual_2x_cost"].get(year, {}) for year in required_years]
    trade_counts = [int(value.get("trades", 0)) for value in annual_rows]
    expectancies = [
        float(value["expectancy"])
        for value in annual_rows
        if value.get("expectancy") is not None
    ]
    return (
        bool(row["historical_stability_pass"]),
        min(trade_counts),
        sum(trade_counts),
        min(expectancies, default=float("-inf")),
        row["aggregate_2x_cost"].get("expectancy") or float("-inf"),
    )


def evaluate(frame: pd.DataFrame, *, combine_simulations: int = 2_000) -> dict[str, Any]:
    dates, sessions, skipped = prepare_sessions(frame)
    rows: list[dict[str, Any]] = []
    configs = parameter_grid()
    for config in configs:
        trades = [trade for day in dates if (trade := simulate_session(sessions[day], config)) is not None]
        delayed = [
            trade
            for day in dates
            if (trade := simulate_session(sessions[day], config, entry_delay_bars=1)) is not None
        ]
        years = sorted({trade.day[:4] for trade in trades})
        row = {
            "config": asdict(config),
            "name": config.name,
            "annual": {year: metrics([trade for trade in trades if trade.day.startswith(year)]) for year in years},
            "annual_2x_cost": {
                year: metrics([trade for trade in trades if trade.day.startswith(year)], cost_multiple=2.0)
                for year in years
            },
            "aggregate": metrics(trades),
            "aggregate_2x_cost": metrics(trades, cost_multiple=2.0),
            "aggregate_3x_cost": metrics(trades, cost_multiple=3.0),
            "aggregate_2x_cost_one_bar_delay": metrics(delayed, cost_multiple=2.0),
            "aggregate_2x_cost_without_top_1pct": metrics(trades, cost_multiple=2.0, remove_top_pct=0.01),
            "exit_reasons": pd.Series([trade.exit_reason for trade in trades]).value_counts().to_dict(),
            "trades": [asdict(trade) for trade in trades],
        }
        row["historical_stability_pass"] = _historical_stability_pass(row)
        rows.append(row)

    rows.sort(key=_candidate_rank, reverse=True)
    best = rows[0] if rows else None
    combine = None
    if best:
        pnl_by_day = {
            trade["day"]: trade_pnl(GapTrade(**trade), cost_multiple=2.0)
            for trade in best["trades"]
        }
        daily = [pnl_by_day.get(day, 0.0) for day in dates]
        rules = CombineRules(max_sessions=252)
        combine = {
            "method": "circular_block_bootstrap_of_2024plus_double_cost_daily_pnl_including_no_trade_days",
            "one_mes": bootstrap_combine(daily, contracts=1, rules=rules, simulations=combine_simulations),
            "two_mes": bootstrap_combine(daily, contracts=2, rules=rules, simulations=combine_simulations),
            "warning": "Consumed-history diagnostic; pass rate is not a forecast or purchase signal.",
        }

    survivors = [row["name"] for row in rows if row["historical_stability_pass"]]
    return {
        "schema_version": 1,
        "experiment": "MES-OPENING-GAP-FADE-01",
        "preregistration": PREREGISTRATION,
        "mode": "research_only_consumed_history_diagnostic",
        "evidence_status": "not_independent_confirmation",
        "execution_enabled": False,
        "can_submit_orders": False,
        "dataset_period": [dates[0], dates[-1]] if dates else None,
        "eligible_sessions": len(dates),
        "skipped_sessions": skipped,
        "family_attempts": len(configs),
        "familywise_alpha": FAMILYWISE_ALPHA,
        "historical_stability_survivor_count": len(survivors),
        "historical_stability_survivors": survivors,
        "top_diagnostic_candidate": best,
        "topstep_combine_diagnostic": combine,
        "promotion": {
            "ready": False,
            "decision": "forward_practice_only" if survivors else "historical_gate_failed",
            "forward_cutoff_exclusive": "2026-07-19",
            "requirements": [
                "at least 60 resolved forward outcomes",
                "at least three forward calendar months",
                "positive 2x-cost forward expectancy",
                "forward profit factor >= 1.20",
                "1-2 MES Combine pass rate >= 0.60 and MLL failure rate <= 0.05",
            ],
        },
        "all_candidates": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--combine-simulations", type=int, default=2_000)
    args = parser.parse_args()
    report = evaluate(pd.read_csv(args.csv), combine_simulations=args.combine_simulations)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    summary = {key: value for key, value in report.items() if key not in {"all_candidates", "top_diagnostic_candidate"}}
    if report["top_diagnostic_candidate"]:
        best = report["top_diagnostic_candidate"]
        summary["top_diagnostic_candidate"] = {
            "name": best["name"],
            "historical_stability_pass": best["historical_stability_pass"],
            "aggregate": best["aggregate"],
            "aggregate_2x_cost": best["aggregate_2x_cost"],
        }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
