#!/usr/bin/env python3
"""Frozen MES structure-break + displacement-FVG challenger.

Research only. It has no broker imports and cannot submit orders.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV = ROOT / "examples" / "mes_v0_1m_2022-01-01_2026-07-19_rth.csv"
DEFAULT_OUT = ROOT / "data" / "breakaway_fvg_structure_results.json"
PREREGISTRATION = "research/BREAKAWAY_FVG_STRUCTURE_PREREGISTRATION_2026-08-04.md"

TICK = 0.25
POINT_USD = 5.0
COMMISSION_PER_SIDE = 1.24
SLIPPAGE_TICKS_PER_SIDE = 1
COST_PER_SIDE = COMMISSION_PER_SIDE + SLIPPAGE_TICKS_PER_SIDE * TICK * POINT_USD
ENTRY_START = "09:45"
ENTRY_END = "11:30"
FLATTEN = "15:55"
STRUCTURE_LOOKBACK = 6
ATR_LENGTH = 14
VOLUME_LENGTH = 20
BODY_ATR_MIN = 0.60
REL_VOLUME_MIN = 1.20
MIN_GAP_TICKS = 4
RETRACE_BARS = 6
MIN_RISK_TICKS = 8
MAX_RISK_TICKS = 40
REWARD_RISK = 2.0
BREAKEVEN_R = 1.0


@dataclass(frozen=True)
class Signal:
    direction: int
    formed_at: pd.Timestamp
    expires_at: pd.Timestamp
    midpoint: float
    stop: float
    risk_points: float
    structure_level: float
    gap_bottom: float
    gap_top: float


def prepare(raw: pd.DataFrame) -> pd.DataFrame:
    frame = raw.copy()
    timestamp_col = "timestamp" if "timestamp" in frame.columns else "dt"
    frame["dt"] = pd.to_datetime(frame[timestamp_col])
    frame["date"] = frame["dt"].dt.date
    frame["time"] = frame["dt"].dt.strftime("%H:%M")
    return frame.sort_values("dt").reset_index(drop=True)


def aggregate_five_minute(bars: pd.DataFrame) -> pd.DataFrame:
    fields = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in bars.columns:
        fields["volume"] = "sum"
    five = bars.set_index("dt").resample("5min", label="left", closed="left").agg(fields).dropna()
    if "volume" not in five.columns:
        five["volume"] = 1.0
    prior_close = five["close"].shift(1)
    true_range = pd.concat(
        [
            five["high"] - five["low"],
            (five["high"] - prior_close).abs(),
            (five["low"] - prior_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    five["atr"] = true_range.rolling(ATR_LENGTH).mean()
    five["prior_volume_mean"] = five["volume"].shift(1).rolling(VOLUME_LENGTH).mean()
    return five


def find_signals(bars: pd.DataFrame) -> list[Signal]:
    five = aggregate_five_minute(bars)
    signals: list[Signal] = []
    for i in range(max(STRUCTURE_LOOKBACK, ATR_LENGTH, VOLUME_LENGTH) + 2, len(five)):
        row = five.iloc[i]
        formed_at = five.index[i] + pd.Timedelta(minutes=5)
        formed_time = formed_at.strftime("%H:%M")
        if formed_time < ENTRY_START or formed_time >= ENTRY_END:
            continue
        atr = float(row["atr"])
        volume_mean = float(row["prior_volume_mean"])
        if not pd.notna(atr) or atr <= 0 or not pd.notna(volume_mean) or volume_mean <= 0:
            continue
        prior = five.iloc[i - STRUCTURE_LOOKBACK:i]
        structure_high = float(prior["high"].max())
        structure_low = float(prior["low"].min())
        body = abs(float(row["close"]) - float(row["open"]))
        relative_volume = float(row["volume"]) / volume_mean
        if body < BODY_ATR_MIN * atr or relative_volume < REL_VOLUME_MIN:
            continue

        two_back = five.iloc[i - 2]
        direction = 0
        gap_bottom = gap_top = structure_level = 0.0
        if (
            float(row["close"]) > structure_high
            and float(row["close"]) > float(row["open"])
            and float(row["low"]) - float(two_back["high"]) >= MIN_GAP_TICKS * TICK
        ):
            direction = 1
            structure_level = structure_high
            gap_bottom = float(two_back["high"])
            gap_top = float(row["low"])
            formation_low = float(five.iloc[i - 2:i + 1]["low"].min())
            stop = min(structure_low, formation_low) - TICK
        elif (
            float(row["close"]) < structure_low
            and float(row["close"]) < float(row["open"])
            and float(two_back["low"]) - float(row["high"]) >= MIN_GAP_TICKS * TICK
        ):
            direction = -1
            structure_level = structure_low
            gap_bottom = float(row["high"])
            gap_top = float(two_back["low"])
            formation_high = float(five.iloc[i - 2:i + 1]["high"].max())
            stop = max(structure_high, formation_high) + TICK
        else:
            continue

        midpoint = (gap_bottom + gap_top) / 2.0
        risk = (midpoint - stop) * direction
        risk_ticks = risk / TICK
        if not MIN_RISK_TICKS <= risk_ticks <= MAX_RISK_TICKS:
            continue
        signals.append(Signal(
            direction=direction,
            formed_at=formed_at,
            expires_at=formed_at + pd.Timedelta(minutes=5 * RETRACE_BARS),
            midpoint=midpoint,
            stop=stop,
            risk_points=risk,
            structure_level=structure_level,
            gap_bottom=gap_bottom,
            gap_top=gap_top,
        ))
    return signals


def first_entry(bars: pd.DataFrame, signals: list[Signal]) -> tuple[Signal, int] | None:
    for signal in signals:
        eligible = bars[(bars["dt"] >= signal.formed_at) & (bars["dt"] < signal.expires_at)]
        for idx, bar in eligible.iterrows():
            if bar["time"] < ENTRY_START or bar["time"] >= ENTRY_END:
                continue
            touched = (
                signal.direction > 0 and float(bar["low"]) <= signal.midpoint
            ) or (
                signal.direction < 0 and float(bar["high"]) >= signal.midpoint
            )
            if touched:
                return signal, int(idx)
    return None


def manage_trade(bars: pd.DataFrame, signal: Signal, entry_idx: int) -> tuple[float, str]:
    entry = signal.midpoint
    direction = signal.direction
    risk = signal.risk_points
    target = entry + direction * REWARD_RISK * risk
    arm_level = entry + direction * BREAKEVEN_R * risk
    breakeven_active = False
    for _, bar in bars.iloc[entry_idx:].iterrows():
        low, high = float(bar["low"]), float(bar["high"])
        if bar["time"] >= FLATTEN:
            return direction * (float(bar["close"]) - entry), "time_flatten"
        adverse_hit = low <= (entry if breakeven_active else signal.stop) if direction > 0 else high >= (entry if breakeven_active else signal.stop)
        target_hit = high >= target if direction > 0 else low <= target
        arm_hit = high >= arm_level if direction > 0 else low <= arm_level
        if adverse_hit:
            return (0.0, "breakeven") if breakeven_active else (-risk, "stop")
        if target_hit:
            return REWARD_RISK * risk, "target"
        if arm_hit:
            breakeven_active = True
    return direction * (float(bars.iloc[-1]["close"]) - entry), "session_end"


def evaluate_session(bars: pd.DataFrame) -> dict | None:
    signals = find_signals(bars)
    entry = first_entry(bars, signals)
    if entry is None:
        return None
    signal, entry_idx = entry
    points, exit_reason = manage_trade(bars, signal, entry_idx)
    return {
        "date": str(bars.iloc[0]["date"]),
        "entry_at": str(bars.iloc[entry_idx]["dt"]),
        "points_before_cost": round(points, 4),
        "exit_reason": exit_reason,
        **asdict(signal),
    }


def summarize(rows: list[dict], *, cost_mult: float = 1.0) -> dict:
    cost = 2 * COST_PER_SIDE * cost_mult
    pnls = [float(row["points_before_cost"]) * POINT_USD - cost for row in rows]
    if not pnls:
        return {"trades": 0, "total_pnl": 0.0, "expectancy": None, "profit_factor": None}
    gross_wins = sum(value for value in pnls if value > 0)
    gross_losses = -sum(value for value in pnls if value <= 0)
    equity = pd.Series([0.0, *pnls]).cumsum()
    return {
        "trades": len(pnls),
        "total_pnl": round(sum(pnls), 2),
        "expectancy": round(sum(pnls) / len(pnls), 2),
        "win_rate": round(sum(value > 0 for value in pnls) / len(pnls), 4),
        "profit_factor": round(gross_wins / gross_losses, 4) if gross_losses > 0 else None,
        "max_drawdown": round(float((equity.cummax() - equity).max()), 2),
        "exit_reasons": {reason: sum(row["exit_reason"] == reason for row in rows) for reason in sorted({row["exit_reason"] for row in rows})},
    }


def build_report(raw: pd.DataFrame) -> dict:
    frame = prepare(raw)
    sessions = sorted(frame["date"].unique())
    dev_end, selection_end = int(len(sessions) * 0.70), int(len(sessions) * 0.85)
    development = sessions[:dev_end]
    selection = sessions[dev_end:selection_end]
    final = sessions[selection_end:]
    by_date = {date: group.reset_index(drop=True) for date, group in frame.groupby("date")}
    rows = [row for date in sessions if (row := evaluate_session(by_date[date])) is not None]
    row_by_date = {pd.Timestamp(row["date"]).date(): row for row in rows}
    third = len(development) // 3
    regimes = [development[:third], development[third:2 * third], development[2 * third:]]
    development_regimes = [summarize([row_by_date[d] for d in dates if d in row_by_date]) for dates in regimes]
    dev_pass = all(
        result.get("trades", 0) >= 30
        and (result.get("expectancy") or 0) > 0
        and (result.get("profit_factor") or 0) > 1.0
        for result in development_regimes
    )
    report = {
        "experiment": "BREAKAWAY-FVG-STRUCTURE-01",
        "preregistration": PREREGISTRATION,
        "mode": "research_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "dataset_sessions": len(sessions),
        "development_sessions": len(development),
        "selection_sessions": len(selection),
        "final_sessions": len(final),
        "development_regimes": development_regimes,
        "development": summarize([row_by_date[d] for d in development if d in row_by_date]),
        "development_2x_cost": summarize([row_by_date[d] for d in development if d in row_by_date], cost_mult=2.0),
        "development_pass": dev_pass,
        "selection_opened": False,
        "final_opened": False,
        "warning": "Public-rule proxy, not the vendor's proprietary implementation or verified performance.",
    }
    if dev_pass:
        selection_rows = [row_by_date[d] for d in selection if d in row_by_date]
        report["selection"] = summarize(selection_rows)
        report["selection_2x_cost"] = summarize(selection_rows, cost_mult=2.0)
        report["selection_opened"] = True
        selection_pass = (
            report["selection"].get("trades", 0) >= 30
            and (report["selection"].get("profit_factor") or 0) >= 1.20
            and (report["selection"].get("expectancy") or 0) > 0
            and (report["selection_2x_cost"].get("expectancy") or 0) > 0
        )
        report["selection_pass"] = selection_pass
        if selection_pass:
            final_rows = [row_by_date[d] for d in final if d in row_by_date]
            report["final"] = summarize(final_rows)
            report["final_2x_cost"] = summarize(final_rows, cost_mult=2.0)
            report["final_opened"] = True
            report["final_pass"] = (
                report["final"].get("trades", 0) >= 30
                and (report["final"].get("profit_factor") or 0) >= 1.20
                and (report["final_2x_cost"].get("expectancy") or 0) > 0
                and (report["final"].get("max_drawdown") or float("inf")) <= 200
            )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = build_report(pd.read_csv(args.csv))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    if args.print_report:
        print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
