#!/usr/bin/env python3
"""Preregistered SPY 12:00 option replay on expired-contract Alpaca data.

Frozen spec: research/OPTIONS_REPLAY_PREREGISTRATION_2026-07-25.md
Read-only data API; no orders; no purchases.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

VIBE_HOME = Path.home() / ".vibe-trading"
SIGNALS_PATH = ROOT / "data" / "green_day_htf_ltf_results_per_checkpoint.json"
NBBO_SAMPLES_PATH = VIBE_HOME / "logs" / "option-quote-samples.jsonl"
OUTPUT_PATH = ROOT / "data" / "options_replay_results.json"

CHECKPOINT = "12:00"
VARIANTS = ("ltf_only", "daily_aligned")
MIN_SIGNAL_DATE = "2024-03-01"
EXIT_WINDOW = ("12:45", "12:59")
SPREAD_FALLBACK_REL = 0.04
MIN_CALIBRATION_SAMPLES = 10
HALF_SPREAD_FLOOR_DOLLARS = 0.02
COMMISSION_ROUND_TRIP = 1.32  # per contract, both sides, incl. fees
CONTRACT_MULTIPLIER = 100.0
DTE_BUCKETS = ("0dte", "1dte", "3_7dte")


def build_occ_symbol(underlying: str, expiry: str, right: str, strike: float) -> str:
    from datetime import datetime as _dt

    day = _dt.strptime(expiry, "%Y-%m-%d")
    return f"{underlying}{day:%y%m%d}{right[0].upper()}{int(round(strike * 1000)):08d}"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def calibrate_spread(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """P75 relative spread from forward NBBO capture; frozen fallback below
    MIN_CALIBRATION_SAMPLES valid SPY samples."""
    rels = []
    for row in samples:
        contract = str(row.get("contract") or "")
        quote = row.get("quote") if isinstance(row.get("quote"), dict) else row
        bid = quote.get("bid")
        ask = quote.get("ask")
        try:
            bid = float(bid)
            ask = float(ask)
        except (TypeError, ValueError):
            continue
        if not contract.startswith("SPY") or bid <= 0 or ask <= bid:
            continue
        mid = (bid + ask) / 2
        rels.append((ask - bid) / mid)
    if len(rels) >= MIN_CALIBRATION_SAMPLES:
        rels.sort()
        rel = rels[min(len(rels) - 1, math.ceil(0.75 * len(rels)) - 1)]
        return {"rel_spread": round(rel, 4), "source": "forward_nbbo_p75", "samples": len(rels)}
    return {"rel_spread": SPREAD_FALLBACK_REL, "source": "frozen_fallback", "samples": len(rels)}


def _regenerate_signal_rows() -> list[dict[str, Any]]:
    """Deterministically rebuild the parent trial's per-checkpoint rows from
    the same frozen code and cached data (results JSON stores summaries
    only)."""
    import pandas as pd

    from research import green_day_htf_ltf_lab as lab

    minute = pd.read_parquet(lab.MINUTE_PATH)
    spy_daily = lab.load_daily("SPY")
    if spy_daily is None:
        raise SystemExit("SPY daily cache missing")
    htf = lab.build_htf_table(spy_daily)
    rows, _coverage = lab.replay_spy(minute, htf, completeness="per_checkpoint")
    return rows


def load_signals(path: Path = SIGNALS_PATH) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    seen = set()
    raw_rows = payload.get("spy_replay_rows") or _regenerate_signal_rows()
    for row in raw_rows:
        if row.get("checkpoint_et") != CHECKPOINT or row.get("variant") not in VARIANTS:
            continue
        if str(row.get("date")) < MIN_SIGNAL_DATE:
            continue
        key = (row["date"], row["direction"])
        if key in seen:
            for existing in rows:
                if (existing["date"], existing["direction"]) == key:
                    existing["variants"].add(row["variant"])
            continue
        seen.add(key)
        rows.append({
            "date": str(row["date"]),
            "direction": str(row["direction"]),
            "underlying_entry": float(row["entry"]),
            "underlying_return_60m_bps": row.get("return_60m_bps"),
            "variants": {row["variant"]},
        })
    for row in rows:
        row["variants"] = sorted(row["variants"])
    return rows


def _next_trading_day(day: date) -> date:
    step = day + timedelta(days=1)
    while step.weekday() >= 5:
        step += timedelta(days=1)
    return step


def candidate_expiries(session: str) -> dict[str, list[str]]:
    day = date.fromisoformat(session)
    out: dict[str, list[str]] = {
        "0dte": [session],
        "1dte": [_next_trading_day(day).isoformat()],
        "3_7dte": [],
    }
    for offset in range(3, 8):
        target = day + timedelta(days=offset)
        if target.weekday() < 5:
            out["3_7dte"].append(target.isoformat())
    return out


def _bars_window_et(bars: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """(HH:MM ET, bar) pairs; converts bar timestamps, never fixed offsets."""
    import pandas as pd

    out = []
    for bar in bars:
        stamp = pd.Timestamp(bar["t"])
        if stamp.tzinfo is None:
            stamp = stamp.tz_localize("UTC")
        out.append((stamp.tz_convert("America/New_York").strftime("%H:%M"), bar))
    return out


def replay_signal(
    signal: dict[str, Any],
    fetch_bars: Callable[[str, str], list[dict[str, Any]]],
    half_spread_rel: float,
) -> dict[str, Any]:
    right = "C" if signal["direction"] == "bull" else "P"
    strike = round(signal["underlying_entry"])
    result: dict[str, Any] = {**{k: signal[k] for k in ("date", "direction", "variants", "underlying_return_60m_bps")}}
    for bucket, expiries in candidate_expiries(signal["date"]).items():
        outcome: dict[str, Any] = {"status": "unavailable"}
        for expiry in expiries:
            occ = build_occ_symbol("SPY", expiry, right, strike)
            bars = fetch_bars(occ, signal["date"])
            if not bars:
                continue
            timed = _bars_window_et(bars)
            entry_bar = next((bar for hhmm, bar in timed if hhmm == CHECKPOINT), None)
            exit_candidates = [bar for hhmm, bar in timed if EXIT_WINDOW[0] <= hhmm <= EXIT_WINDOW[1]]
            if entry_bar is None or not exit_candidates:
                outcome = {"status": "skipped_missing_bars", "occ": occ}
                break
            entry_price = float(entry_bar["o"])
            exit_price = float(exit_candidates[-1]["c"])
            half = max(entry_price * half_spread_rel / 2, HALF_SPREAD_FLOOR_DOLLARS)
            buy = entry_price + half
            half_exit = max(exit_price * half_spread_rel / 2, HALF_SPREAD_FLOOR_DOLLARS)
            sell = max(0.0, exit_price - half_exit)
            pnl = (sell - buy) * CONTRACT_MULTIPLIER - COMMISSION_ROUND_TRIP
            outcome = {
                "status": "filled",
                "occ": occ,
                "expiry": expiry,
                "entry_mid": entry_price,
                "exit_mid": exit_price,
                "buy": round(buy, 4),
                "sell": round(sell, 4),
                "pnl_dollars_per_contract": round(pnl, 2),
                "return_pct": round((sell / buy - 1) * 100 - (COMMISSION_ROUND_TRIP / (buy * CONTRACT_MULTIPLIER)) * 100, 3),
            }
            break
        result[bucket] = outcome
    return result


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for variant in VARIANTS:
        out[variant] = {}
        subset = [row for row in rows if variant in row["variants"]]
        for bucket in DTE_BUCKETS:
            filled = [row[bucket] for row in subset if row.get(bucket, {}).get("status") == "filled"]
            returns = [row["return_pct"] for row in filled]
            wins = [value for value in returns if value > 0]
            losses = [value for value in returns if value < 0]
            trimmed = sorted(returns)[:-max(1, math.ceil(len(returns) * 0.01))] if len(returns) > 1 else []
            out[variant][bucket] = {
                "signals": len(subset),
                "filled": len(filled),
                "skipped_or_unavailable": len(subset) - len(filled),
                "mean_return_pct": round(sum(returns) / len(returns), 3) if returns else None,
                "win_rate": round(len(wins) / len(returns), 3) if returns else None,
                "profit_factor": (
                    round(sum(wins) / abs(sum(losses)), 3) if losses else ("inf" if wins else None)
                ),
                "top_one_pct_removed_mean": (
                    round(sum(trimmed) / len(trimmed), 3) if trimmed else None
                ),
            }
    return out


def _alpaca_fetch_bars(headers: dict[str, str]) -> Callable[[str, str], list[dict[str, Any]]]:
    import requests

    def fetch(occ: str, day: str) -> list[dict[str, Any]]:
        try:
            resp = requests.get(
                "https://data.alpaca.markets/v1beta1/options/bars",
                headers=headers,
                params={
                    "symbols": occ,
                    "timeframe": "1Min",
                    "start": f"{day}T13:00:00Z",
                    "end": f"{day}T21:00:00Z",
                    "limit": 10000,
                },
                timeout=20,
            )
        except requests.RequestException:
            return []
        if resp.status_code != 200:
            return []
        bars = (resp.json() or {}).get("bars") or {}
        rows = bars.get(occ)
        return rows if isinstance(rows, list) else []

    return fetch


def run(fetch_bars: Callable[[str, str], list[dict[str, Any]]] | None = None) -> dict[str, Any]:
    from datetime import datetime, timezone

    calibration = calibrate_spread(_read_jsonl(NBBO_SAMPLES_PATH))
    signals = load_signals()
    if fetch_bars is None:
        try:
            from dotenv import load_dotenv

            load_dotenv(ROOT / "agent" / ".env")
        except ImportError:
            pass
        key = os.getenv("ALPACA_API_KEY", "")
        secret = os.getenv("ALPACA_SECRET_KEY", "")
        if not key or not secret:
            raise SystemExit("ALPACA_API_KEY / ALPACA_SECRET_KEY not configured")
        fetch_bars = _alpaca_fetch_bars({"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret})
    rows = [replay_signal(signal, fetch_bars, calibration["rel_spread"]) for signal in signals]
    return {
        "provider": "options_replay_lab",
        "mode": "read_only_preregistered_replay",
        "execution_enabled": False,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "preregistration": "research/OPTIONS_REPLAY_PREREGISTRATION_2026-07-25.md",
        "spread_calibration": calibration,
        "commission_round_trip_dollars": COMMISSION_ROUND_TRIP,
        "signal_count": len(rows),
        "summaries": summarize(rows),
        "rows": rows,
        "warnings": [
            "2024-03+ dates were consumed by the parent trial; diagnostic only.",
            "Bar open/close are trade-derived prices; spread stress is calibrated, not observed NBBO.",
            "No promotion or production change may result directly from this run.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    report = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "signal_count": report["signal_count"],
        "spread_calibration": report["spread_calibration"],
        "summaries": report["summaries"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
