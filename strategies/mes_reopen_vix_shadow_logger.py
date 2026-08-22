"""Topstep-compliant MES reopen-to-open shadow logger.

This module observes a frozen signal and cannot submit orders. Yahoo intraday
bars are a free forward-shadow proxy; promotion requires executable quote
reconciliation before practice execution is considered.
"""
from __future__ import annotations

import argparse
import json
import os
import warnings
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = ROOT / "data" / "mes_reopen_vix_shadow_log.jsonl"
PREREGISTRATION = "research/MES_REOPEN_VIX_FILTER_PREREGISTRATION_2026-08-17.md"
ET = ZoneInfo("America/New_York")
VIX_CAP = 18.0
PRIOR_MOVE_FLOOR = -0.01
POINT_VALUE = 5.0
FRICTION_ROUND_TRIP = 3.98


def _flatten_columns(frame: pd.DataFrame) -> pd.DataFrame:
    if isinstance(frame.columns, pd.MultiIndex):
        frame = frame.copy()
        frame.columns = frame.columns.get_level_values(0)
    return frame


def _to_et(frame: pd.DataFrame) -> pd.DataFrame:
    frame = _flatten_columns(frame).sort_index()
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise TypeError("market data must use a DatetimeIndex")
    if frame.index.tz is None:
        frame.index = frame.index.tz_localize("America/New_York")
    else:
        frame.index = frame.index.tz_convert("America/New_York")
    return frame


def download_mes_intraday() -> pd.DataFrame:
    import yfinance as yf

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return yf.download(
            "MES=F",
            period="15d",
            interval="5m",
            auto_adjust=False,
            prepost=True,
            progress=False,
        )


def download_vix_daily() -> pd.DataFrame:
    import yfinance as yf

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return yf.download(
            "^VIX",
            period="15d",
            interval="1d",
            auto_adjust=False,
            progress=False,
        )


def _session_rows(frame: pd.DataFrame, session_date: date, start: str, end: str) -> pd.DataFrame:
    frame = _to_et(frame)
    rows = frame[frame.index.date == session_date]
    return rows.between_time(start, end)


def build_entry_context(
    mes: pd.DataFrame,
    vix: pd.DataFrame,
    trade_date: date,
) -> dict:
    if trade_date.weekday() not in {0, 1, 2, 3}:
        raise ValueError("entry weekday is outside Monday-Thursday")

    mes = _to_et(mes)
    rth = mes.between_time("15:55", "16:00")
    rth = rth[rth.index.date <= trade_date]
    daily_close = rth["Close"].groupby(rth.index.date).last().dropna()
    if trade_date not in daily_close.index:
        raise ValueError("same-day MES 16:00 close is unavailable")
    prior_dates = [value for value in daily_close.index if value < trade_date]
    if not prior_dates:
        raise ValueError("prior-session MES 16:00 close is unavailable")

    entry_rows = _session_rows(mes, trade_date, "18:00", "18:05")
    if entry_rows.empty or pd.isna(entry_rows["Open"].iloc[0]):
        raise ValueError("same-day MES reopen bar is unavailable")

    vix = _flatten_columns(vix).copy()
    if not isinstance(vix.index, pd.DatetimeIndex):
        raise TypeError("VIX data must use a DatetimeIndex")
    vix_dates = pd.Index(vix.index.date)
    exact = vix.loc[vix_dates == trade_date, "Close"].dropna()
    if exact.empty:
        raise ValueError("same-day final VIX close is unavailable")

    current_close = float(daily_close.loc[trade_date])
    prior_close = float(daily_close.loc[prior_dates[-1]])
    prior_move = current_close / prior_close - 1.0
    vix_close = float(exact.iloc[-1])
    entry_row = entry_rows.iloc[0]
    entry_timestamp = entry_rows.index[0]
    return {
        "trade_date": trade_date.isoformat(),
        "entry_timestamp": entry_timestamp.isoformat(),
        "entry_price": float(entry_row["Open"]),
        "mes_close": current_close,
        "prior_mes_close": prior_close,
        "prior_move": prior_move,
        "vix_close": vix_close,
        "vix_pass": vix_close <= VIX_CAP,
        "prior_move_pass": prior_move >= PRIOR_MOVE_FLOOR,
    }


def build_exit_context(mes: pd.DataFrame, exit_date: date) -> dict:
    rows = _session_rows(mes, exit_date, "09:30", "09:35")
    if rows.empty or pd.isna(rows["Open"].iloc[0]):
        raise ValueError("same-day MES 09:30 open bar is unavailable")
    return {
        "exit_date": exit_date.isoformat(),
        "exit_timestamp": rows.index[0].isoformat(),
        "exit_price": float(rows["Open"].iloc[0]),
    }


def _records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def append_record(record: dict, path: Path = LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def _replace_records(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _unsettled_entry(path: Path) -> dict | None:
    candidates = [
        row
        for row in _records(path)
        if row.get("mode") == "entry" and row.get("should_enter") and not row.get("settled")
    ]
    return candidates[-1] if candidates else None


def _base_record(mode: str, as_of: datetime) -> dict:
    return {
        "mode": mode,
        "timestamp": as_of.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "preregistration": PREREGISTRATION,
        "strategy_id": "mes_reopen_vix_shadow_v1",
        "data_source": "yfinance_proxy_MES=F_5m_and_VIX_daily",
        "execution_mode": "shadow_only",
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def run_entry(
    *,
    as_of: datetime | None = None,
    mes: pd.DataFrame | None = None,
    vix: pd.DataFrame | None = None,
    log_path: Path = LOG_PATH,
) -> int:
    as_of = as_of or datetime.now(ET)
    trade_date = as_of.astimezone(ET).date()
    key = f"{trade_date.isoformat()}:MES_reopen_vix_v1"
    existing = _records(log_path)
    if any(row.get("mode") == "entry" and row.get("trade_key") == key for row in existing):
        print(json.dumps({"status": "duplicate_ignored", "trade_key": key}))
        return 0
    if _unsettled_entry(log_path):
        record = _base_record("entry", as_of) | {
            "trade_key": key,
            "should_enter": False,
            "reason": "prior_shadow_entry_unsettled",
        }
        append_record(record, log_path)
        print(json.dumps(record))
        return 0

    try:
        context = build_entry_context(
            download_mes_intraday() if mes is None else mes,
            download_vix_daily() if vix is None else vix,
            trade_date,
        )
        should_enter = bool(context["vix_pass"] and context["prior_move_pass"])
        record = _base_record("entry", as_of) | context | {
            "trade_key": key,
            "vix_cap": VIX_CAP,
            "prior_move_floor": PRIOR_MOVE_FLOOR,
            "friction_round_trip_dollar": FRICTION_ROUND_TRIP,
            "should_enter": should_enter,
            "settled": not should_enter,
            "reason": "eligible" if should_enter else "filter_not_met",
        }
    except Exception as exc:
        record = _base_record("entry", as_of) | {
            "trade_key": key,
            "should_enter": False,
            "settled": True,
            "reason": "market_data_incomplete",
            "error": str(exc),
        }
    append_record(record, log_path)
    print(json.dumps(record))
    return 0


def run_exit(
    *,
    as_of: datetime | None = None,
    mes: pd.DataFrame | None = None,
    log_path: Path = LOG_PATH,
) -> int:
    as_of = as_of or datetime.now(ET)
    entry = _unsettled_entry(log_path)
    if entry is None:
        record = _base_record("exit", as_of) | {"reason": "no_unsettled_shadow_entry"}
        append_record(record, log_path)
        print(json.dumps(record))
        return 0

    try:
        context = build_exit_context(
            download_mes_intraday() if mes is None else mes,
            as_of.astimezone(ET).date(),
        )
        entry_price = float(entry["entry_price"])
        exit_price = float(context["exit_price"])
        gross = (exit_price - entry_price) * POINT_VALUE
        net = gross - FRICTION_ROUND_TRIP
        record = _base_record("exit", as_of) | context | {
            "trade_key": entry["trade_key"],
            "entry_timestamp": entry["entry_timestamp"],
            "entry_price": entry_price,
            "gross_dollar": round(gross, 2),
            "friction_round_trip_dollar": FRICTION_ROUND_TRIP,
            "net_dollar": round(net, 2),
            "outcome": "win" if net > 0 else ("loss" if net < 0 else "flat"),
            "reason": "resolved",
        }
    except Exception as exc:
        record = _base_record("exit", as_of) | {
            "trade_key": entry.get("trade_key"),
            "reason": "market_data_incomplete",
            "error": str(exc),
        }
        append_record(record, log_path)
        print(json.dumps(record))
        return 0

    rows = _records(log_path)
    for row in rows:
        if row.get("mode") == "entry" and row.get("trade_key") == entry["trade_key"]:
            row["settled"] = True
    rows.append(record)
    _replace_records(rows, log_path)
    print(json.dumps(record))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("entry", "exit"), required=True)
    args = parser.parse_args()
    return run_entry() if args.mode == "entry" else run_exit()


if __name__ == "__main__":
    raise SystemExit(main())
