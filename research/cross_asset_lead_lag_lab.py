#!/usr/bin/env python3
"""Preregistered delayed cross-asset lead-lag test for MES."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from statistics import NormalDist
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MES_QUOTES = ROOT / "data" / "databento" / "mes_v0_bbo1s_rth.parquet"
CACHE = ROOT / "data" / "cross_asset_5m_2026-08-04.csv"
OUTPUT = ROOT / "data" / "cross_asset_lead_lag_results.json"
LEADERS = {"SPY": 1, "QQQ": 1, "HYG": 1, "TLT": -1, "^VIX": -1}
MIN_DEVELOPMENT_TRADES = 60
MIN_HOLDOUT_TRADES = 25
CORRECTED_ALPHA = 0.05 / 520
MES_POINT_VALUE = 5.0
MES_TICK = 0.25
BASE_COMMISSION = 2.48


@dataclass(frozen=True)
class Metrics:
    trades: int
    expectancy_dollars: float | None
    profit_factor: float | None
    win_rate: float | None
    one_sided_p: float | None


def _metrics(values: list[float]) -> Metrics:
    if not values:
        return Metrics(0, None, None, None, None)
    mean = sum(values) / len(values)
    wins = sum(value > 0 for value in values)
    gross_win = sum(value for value in values if value > 0)
    gross_loss = -sum(value for value in values if value < 0)
    pf = math.inf if gross_loss == 0 and gross_win > 0 else (gross_win / gross_loss if gross_loss else 0.0)
    p_value = None
    if len(values) >= 2:
        variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
        if variance > 0:
            z_score = mean / math.sqrt(variance / len(values))
            p_value = 1.0 - NormalDist().cdf(z_score)
    return Metrics(
        len(values), round(mean, 6), round(pf, 6) if math.isfinite(pf) else math.inf,
        round(wins / len(values), 6), round(p_value, 10) if p_value is not None else None,
    )


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_leaders(path: Path = CACHE) -> Path:
    import pandas as pd
    import yfinance as yf

    frame = yf.download(
        list(LEADERS), period="60d", interval="5m", auto_adjust=False,
        prepost=False, progress=False, group_by="column", threads=False,
    )
    if frame.empty:
        raise RuntimeError("leader_download_empty")
    closes = frame["Close"] if isinstance(frame.columns, pd.MultiIndex) else frame[["Close"]]
    if not isinstance(closes, pd.DataFrame):
        closes = closes.to_frame()
    closes.index = pd.to_datetime(closes.index, utc=True)
    closes.index.name = "ts"
    closes = closes.rename(columns={str(column): str(column) for column in closes.columns})
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    closes.to_csv(temp)
    os.replace(temp, path)
    return path


def load_leaders(path: Path) -> Any:
    import pandas as pd

    frame = pd.read_csv(path, parse_dates=["ts"]).set_index("ts").sort_index()
    frame.index = pd.to_datetime(frame.index, utc=True)
    return frame


def load_mes_bars(start: Any, end: Any, path: Path = MES_QUOTES) -> Any:
    import duckdb
    import pandas as pd

    connection = duckdb.connect()
    columns = [row[0] for row in connection.execute(
        "DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]
    ).fetchall()]
    timestamp = "ts_recv" if "ts_recv" in columns else "ts_event"
    bid = "bid_px_00" if "bid_px_00" in columns else "bid_px"
    ask = "ask_px_00" if "ask_px_00" in columns else "ask_px"
    query = f"""
        SELECT
          time_bucket(INTERVAL '5 minutes', {timestamp}) AS ts,
          arg_min({ask}, {timestamp}) AS entry_ask,
          arg_min({bid}, {timestamp}) AS entry_bid,
          arg_max({ask}, {timestamp}) AS exit_ask,
          arg_max({bid}, {timestamp}) AS exit_bid
        FROM read_parquet(?)
        WHERE {timestamp} >= ? AND {timestamp} < ?
        GROUP BY 1 ORDER BY 1
    """
    frame = connection.execute(query, [str(path), start.to_pydatetime(), end.to_pydatetime()]).fetchdf()
    if frame.empty:
        return frame
    frame["ts"] = pd.to_datetime(frame["ts"], utc=True)
    numeric = ["entry_ask", "entry_bid", "exit_ask", "exit_bid"]
    scale = 1e-9 if float(frame[numeric].stack().median()) > 1e6 else 1.0
    frame[numeric] = frame[numeric].astype(float) * scale
    return frame.set_index("ts").sort_index()


def evaluate(leader_close: Any, mes: Any, relation: int) -> list[dict[str, Any]]:
    import pandas as pd

    returns = leader_close.pct_change()
    trailing_mean = returns.rolling(20, min_periods=20).mean()
    trailing_std = returns.rolling(20, min_periods=20).std(ddof=1)
    z_score = (returns - trailing_mean) / trailing_std.replace(0, math.nan)
    signal = (z_score.abs() >= 1.5) & z_score.notna()
    rows: list[dict[str, Any]] = []
    for known_at, z_value in z_score[signal].items():
        entry_interval = known_at + pd.Timedelta(minutes=5)
        if entry_interval not in mes.index:
            continue
        quote = mes.loc[entry_interval]
        if isinstance(quote, pd.DataFrame):
            quote = quote.iloc[0]
        direction = relation * (1 if float(z_value) > 0 else -1)
        if direction > 0:
            gross = (float(quote["exit_bid"]) - float(quote["entry_ask"])) * MES_POINT_VALUE
        else:
            gross = (float(quote["entry_bid"]) - float(quote["exit_ask"])) * MES_POINT_VALUE
        rows.append({
            "known_at": known_at.isoformat(), "entry_at": entry_interval.isoformat(),
            "session": entry_interval.date().isoformat(), "z_score": round(float(z_value), 6),
            "direction": direction, "base_pnl": gross - BASE_COMMISSION,
            "stress_pnl": gross - 2 * BASE_COMMISSION - 2 * MES_TICK * MES_POINT_VALUE,
        })
    return rows


def run(cache: Path = CACHE, output: Path = OUTPUT, *, download: bool = False) -> dict[str, Any]:
    if download or not cache.exists():
        download_leaders(cache)
    leaders = load_leaders(cache)
    start, end = leaders.index.min(), leaders.index.max() + __import__("pandas").Timedelta(minutes=5)
    mes = load_mes_bars(start, end)
    common_sessions = sorted(set(mes.index.date))
    split = int(len(common_sessions) * 0.70)
    development_sessions = {value.isoformat() for value in common_sessions[:split]}
    holdout_sessions = {value.isoformat() for value in common_sessions[split:]}
    hypotheses: dict[str, Any] = {}
    for symbol, relation in LEADERS.items():
        if symbol not in leaders.columns:
            hypotheses[symbol] = {"status": "missing_leader_series", "holdout_opened": False}
            continue
        trades = evaluate(leaders[symbol].dropna(), mes, relation)
        development = [row for row in trades if row["session"] in development_sessions]
        holdout = [row for row in trades if row["session"] in holdout_sessions]
        base = _metrics([row["base_pnl"] for row in development])
        stress = _metrics([row["stress_pnl"] for row in development])
        survives = (
            base.trades >= MIN_DEVELOPMENT_TRADES
            and (base.expectancy_dollars or 0) > 0
            and (stress.expectancy_dollars or 0) > 0
            and (stress.profit_factor or 0) >= 1.20
            and stress.one_sided_p is not None and stress.one_sided_p < CORRECTED_ALPHA
        )
        item: dict[str, Any] = {
            "status": "development_survivor" if survives else "rejected_development",
            "relation": relation, "development": {"base": base.__dict__, "stress": stress.__dict__},
            "holdout_opened": survives,
        }
        if survives:
            holdout_base = _metrics([row["base_pnl"] for row in holdout])
            holdout_stress = _metrics([row["stress_pnl"] for row in holdout])
            item["holdout"] = {"base": holdout_base.__dict__, "stress": holdout_stress.__dict__}
            item["holdout_pass"] = (
                holdout_base.trades >= MIN_HOLDOUT_TRADES
                and (holdout_base.expectancy_dollars or 0) > 0
                and (holdout_stress.expectancy_dollars or 0) > 0
            )
        hypotheses[symbol] = item
    report = {
        "provider": "cross_asset_lead_lag_lab", "mode": "read_only_research",
        "execution_enabled": False, "can_submit_orders": False,
        "leader_source": "yahoo_finance_unadjusted_5m_research_only",
        "mes_source": "databento_glbx_mdp3_bbo_1s",
        "cache": {"path": str(cache), "sha256": _sha256(cache)},
        "common_session_count": len(common_sessions), "development_session_count": split,
        "sealed_holdout_session_count": len(common_sessions) - split,
        "corrected_alpha": CORRECTED_ALPHA, "hypotheses": hypotheses,
        "survivor_count": sum(item.get("status") == "development_survivor" for item in hypotheses.values()),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(output.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temp, output)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--cache", type=Path, default=CACHE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = run(args.cache, args.output, download=args.download)
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"sessions={report['common_session_count']} survivors={report['survivor_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

