#!/usr/bin/env python3
"""Underlying-distribution audit for the public SPX weekly -1 ATR spread.

This deliberately does not backfill option credits. Daily index closes can
audit level construction and settlement loss, but only point-in-time SPXW
quotes can establish trade profitability.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "spx_weekly_atr_put_spread_underlying_audit.json"


@dataclass(frozen=True)
class DailyBar:
    session_date: date
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class WeeklyBar:
    week_ending: date
    first_session: date
    last_session: date
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class SettlementProxyTrade:
    week_ending: str
    first_session: str
    prior_week_close: float
    prior_week_atr14: float
    raw_short_level: float
    short_strike: float
    long_strike: float
    first_open: float
    settlement_close_proxy: float
    settled_below_short: bool
    settled_through_long: bool
    intrinsic_loss_points: float
    opened_below_short_proxy: bool


def _finite(value: Any) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"non-finite market value: {value!r}")
    return number


def round_half_up_to_increment(value: float, increment: float = 5.0) -> float:
    if increment <= 0:
        raise ValueError("increment must be positive")
    return math.floor((value / increment) + 0.5) * increment


def friday_bucket(day: date) -> date:
    return day + timedelta(days=(4 - day.weekday()) % 7)


def aggregate_daily_to_weekly(rows: Iterable[DailyBar]) -> list[WeeklyBar]:
    ordered = sorted(rows, key=lambda row: row.session_date)
    groups: dict[date, list[DailyBar]] = {}
    for row in ordered:
        if row.session_date.weekday() >= 5:
            continue
        groups.setdefault(friday_bucket(row.session_date), []).append(row)
    result: list[WeeklyBar] = []
    for week_ending, bars in sorted(groups.items()):
        result.append(
            WeeklyBar(
                week_ending=week_ending,
                first_session=bars[0].session_date,
                last_session=bars[-1].session_date,
                open=bars[0].open,
                high=max(row.high for row in bars),
                low=min(row.low for row in bars),
                close=bars[-1].close,
            )
        )
    return result


def weekly_true_ranges(bars: Sequence[WeeklyBar]) -> list[float]:
    ranges: list[float] = []
    for index, bar in enumerate(bars):
        if index == 0:
            ranges.append(bar.high - bar.low)
            continue
        previous_close = bars[index - 1].close
        ranges.append(max(bar.high - bar.low, abs(bar.high - previous_close), abs(bar.low - previous_close)))
    return ranges


def wilder_rma(values: Sequence[float], length: int = 14) -> list[float | None]:
    if length <= 0:
        raise ValueError("length must be positive")
    output: list[float | None] = [None] * len(values)
    if len(values) < length:
        return output
    seed = sum(_finite(value) for value in values[:length]) / length
    output[length - 1] = seed
    previous = seed
    for index in range(length, len(values)):
        previous = ((previous * (length - 1)) + _finite(values[index])) / length
        output[index] = previous
    return output


def build_settlement_proxy_trades(
    bars: Sequence[WeeklyBar], *, atr_length: int = 14, wing_width: float = 50.0
) -> list[SettlementProxyTrade]:
    if wing_width <= 0:
        raise ValueError("wing_width must be positive")
    atr_values = wilder_rma(weekly_true_ranges(bars), atr_length)
    trades: list[SettlementProxyTrade] = []
    for index in range(1, len(bars)):
        prior_atr = atr_values[index - 1]
        if prior_atr is None:
            continue
        prior = bars[index - 1]
        current = bars[index]
        raw_level = prior.close - prior_atr
        short = round_half_up_to_increment(raw_level, 5.0)
        long = short - wing_width
        intrinsic = min(max(short - current.close, 0.0), wing_width)
        trades.append(
            SettlementProxyTrade(
                week_ending=current.week_ending.isoformat(),
                first_session=current.first_session.isoformat(),
                prior_week_close=round(prior.close, 6),
                prior_week_atr14=round(prior_atr, 6),
                raw_short_level=round(raw_level, 6),
                short_strike=round(short, 6),
                long_strike=round(long, 6),
                first_open=round(current.open, 6),
                settlement_close_proxy=round(current.close, 6),
                settled_below_short=current.close < short,
                settled_through_long=current.close <= long,
                intrinsic_loss_points=round(intrinsic, 6),
                opened_below_short_proxy=current.open < short,
            )
        )
    return trades


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if total <= 0:
        return 0.0, 0.0
    p = successes / total
    denominator = 1.0 + (z * z / total)
    centre = p + (z * z / (2.0 * total))
    margin = z * math.sqrt((p * (1.0 - p) / total) + (z * z / (4.0 * total * total)))
    return (centre - margin) / denominator, (centre + margin) / denominator


def _max_drawdown(pnls: Sequence[float]) -> float:
    equity = 0.0
    peak = 0.0
    maximum = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        maximum = max(maximum, peak - equity)
    return maximum


def _max_consecutive_losses(pnls: Sequence[float]) -> int:
    current = 0
    maximum = 0
    for pnl in pnls:
        current = current + 1 if pnl < 0 else 0
        maximum = max(maximum, current)
    return maximum


def summarize(
    trades: Sequence[SettlementProxyTrade],
    *,
    credit_points: float = 2.98,
    commission_dollars: float = 2.64,
) -> dict[str, Any]:
    total = len(trades)
    commission_points = commission_dollars / 100.0
    losses = sum(row.settled_below_short for row in trades)
    full_losses = sum(row.settled_through_long for row in trades)
    wins = total - losses
    lower, upper = wilson_interval(losses, total)
    intrinsic = [row.intrinsic_loss_points for row in trades]
    pnls_points = [credit_points - value - commission_points for value in intrinsic]
    gains = sum(value for value in pnls_points if value > 0)
    pain = -sum(value for value in pnls_points if value < 0)
    return {
        "trades": total,
        "settled_above_short": wins,
        "win_rate": round(wins / total, 6) if total else None,
        "settled_below_short": losses,
        "settled_below_short_rate": round(losses / total, 6) if total else None,
        "settled_below_short_wilson_95": [round(lower, 6), round(upper, 6)],
        "settled_through_long": full_losses,
        "settled_through_long_rate": round(full_losses / total, 6) if total else None,
        "opened_below_short_proxy": sum(row.opened_below_short_proxy for row in trades),
        "average_intrinsic_loss_points": round(sum(intrinsic) / total, 6) if total else None,
        "required_average_gross_credit_points": round((sum(intrinsic) / total) + commission_points, 6) if total else None,
        "constant_credit_sensitivity_only": {
            "gross_credit_points": credit_points,
            "commission_dollars": commission_dollars,
            "average_net_pnl_dollars": round((sum(pnls_points) / total) * 100.0, 2) if total else None,
            "total_net_pnl_dollars": round(sum(pnls_points) * 100.0, 2),
            "profit_factor": round(gains / pain, 6) if pain > 0 else None,
            "max_drawdown_dollars": round(_max_drawdown(pnls_points) * 100.0, 2),
            "max_consecutive_losing_weeks": _max_consecutive_losses(pnls_points),
            "worst_week_dollars": round(min(pnls_points, default=0.0) * 100.0, 2),
        },
    }


def _parse_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def load_daily_csv(path: Path) -> list[DailyBar]:
    rows: list[DailyBar] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            lowered = {str(key).strip().lower(): value for key, value in raw.items()}
            rows.append(
                DailyBar(
                    session_date=_parse_date(lowered["date"]),
                    open=_finite(lowered["open"]),
                    high=_finite(lowered["high"]),
                    low=_finite(lowered["low"]),
                    close=_finite(lowered["close"]),
                )
            )
    return rows


def download_daily(symbol: str = "^GSPC", start: str = "1998-01-01") -> list[DailyBar]:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError("yfinance is required when --csv is not supplied") from exc
    frame = yf.download(symbol, start=start, auto_adjust=False, progress=False)
    if frame.empty:
        raise RuntimeError(f"no daily data returned for {symbol}")
    if getattr(frame.columns, "nlevels", 1) > 1:
        frame.columns = frame.columns.get_level_values(0)
    rows: list[DailyBar] = []
    current_et_date = datetime.now(ZoneInfo("America/New_York")).date()
    for timestamp, raw in frame.iterrows():
        session_date = _parse_date(timestamp)
        if session_date >= current_et_date:
            continue
        rows.append(
            DailyBar(
                session_date=session_date,
                open=_finite(raw["Open"]),
                high=_finite(raw["High"]),
                low=_finite(raw["Low"]),
                close=_finite(raw["Close"]),
            )
        )
    return rows


def build_report(
    rows: Sequence[DailyBar],
    *,
    symbol: str,
    source: str,
    as_of_date: date | None = None,
) -> dict[str, Any]:
    current_et_date = as_of_date or datetime.now(ZoneInfo("America/New_York")).date()
    active_week_ending = friday_bucket(current_et_date)
    weekly = [row for row in aggregate_daily_to_weekly(rows) if row.week_ending < active_week_ending]
    trades = build_settlement_proxy_trades(weekly)
    windows = {
        "full_available": None,
        "source_claim_window_2020_05_plus": date(2020, 5, 8),
        "recent_2025_plus": date(2025, 1, 1),
    }
    summaries: dict[str, Any] = {}
    for name, start in windows.items():
        selected = trades if start is None else [row for row in trades if date.fromisoformat(row.week_ending) >= start]
        summaries[name] = {
            "credit_2_98": summarize(selected, credit_points=2.98),
            "credit_2_73": summarize(selected, credit_points=2.73),
            "credit_2_48": summarize(selected, credit_points=2.48),
        }
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strategy": "spx_weekly_minus_1atr_50wide_put_credit_spread",
        "symbol": symbol,
        "source": source,
        "authority": "underlying_settlement_proxy_only_no_historical_option_quotes",
        "formula": {
            "atr": "14_week_wilder_rma_of_weekly_true_range_seeded_with_14_week_sma",
            "short_strike": "round_half_up_to_5(prior_week_close_minus_prior_week_atr14)",
            "long_strike": "short_strike_minus_50",
            "settlement": "last_available_index_close_in_friday_week_bucket_proxy",
            "spread_intrinsic_loss": "min(max(short_strike_minus_settlement,0),50)",
        },
        "limitations": [
            "Daily close is a proxy until official Cboe SPXW settlement values are reconciled.",
            "The active New York trading week is excluded because its SPXW settlement is incomplete.",
            "Constant-credit scenarios are sensitivities and cannot reproduce historical option profitability.",
            "Monday 10:00 ET point-in-time natural bid/ask quotes are required before promotion.",
        ],
        "external_claims_not_accepted_as_repo_evidence": {
            "win_rate": 0.954,
            "midpoint_profit_factor": 2.48,
            "natural_fill_profit_factor": 2.09,
            "average_credit_points": 2.98,
        },
        "summaries": summaries,
        "sample": {
            "daily_rows": len(rows),
            "weekly_rows": len(weekly),
            "proxy_trades": len(trades),
            "first_trade": trades[0].week_ending if trades else None,
            "last_trade": trades[-1].week_ending if trades else None,
        },
        "promotion": {
            "status": "research_candidate_unverified",
            "execution_enabled": False,
            "can_submit_orders": False,
            "can_change_gates_or_sizing": False,
            "historical_spxw_quotes_required": True,
            "forward_shadow_weeks_required": 52,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--symbol", default="^GSPC")
    parser.add_argument("--start", default="1998-01-01")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    rows = load_daily_csv(args.csv) if args.csv else download_daily(args.symbol, args.start)
    report = build_report(rows, symbol=args.symbol, source=str(args.csv) if args.csv else "yfinance_daily_unadjusted")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
