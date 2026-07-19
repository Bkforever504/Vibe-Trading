#!/usr/bin/env python3
"""Estimate and fetch deep CME minute bars from Databento safely."""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATASET = "GLBX.MDP3"
SCHEMA = "ohlcv-1m"
NY = "America/New_York"


@dataclass(frozen=True)
class DownloadSpec:
    product: str
    start: str
    end: str

    @property
    def symbol(self) -> str:
        return f"{self.product.upper()}.v.0"


def _load_api_key() -> str:
    key = os.getenv("DATABENTO_API_KEY", "").strip()
    if key:
        return key
    env_path = ROOT / "agent" / ".env"
    if env_path.exists():
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            if raw.startswith("DATABENTO_API_KEY="):
                return raw.split("=", 1)[1].strip()
    raise RuntimeError("DATABENTO_API_KEY is not configured")


def request_kwargs(spec: DownloadSpec) -> dict[str, object]:
    return {
        "dataset": DATASET,
        "schema": SCHEMA,
        "symbols": spec.symbol,
        "stype_in": "continuous",
        "start": spec.start,
        "end": spec.end,
    }


def normalize_rth(
    frame: pd.DataFrame,
    *,
    excluded_condition_dates: set[str] | None = None,
) -> tuple[pd.DataFrame, list[str], list[dict[str, object]]]:
    """Convert a Databento frame to ET RTH bars and remove rollover sessions.

    Returns (bars, excluded_roll_sessions, roll_transitions). Each transition is
    mapped to the first RTH session actually present in the data at or after the
    transition timestamp, so Sunday/overnight rolls exclude the following RTH
    session instead of the empty roll calendar date.
    """
    if frame.empty:
        raise ValueError("Databento returned no bars")
    data = frame.copy()
    data.index = pd.to_datetime(data.index, utc=True).tz_convert(NY)
    data = data.sort_index()
    if data.index.has_duplicates:
        data = data[~data.index.duplicated(keep="last")]

    transitions: list[dict[str, object]] = []
    if "instrument_id" in data.columns:
        changed = data["instrument_id"].ne(data["instrument_id"].shift())
        for timestamp in data.index[changed][1:]:
            position = data.index.get_loc(timestamp)
            transitions.append(
                {
                    "timestamp": timestamp.isoformat(),
                    "old_instrument_id": int(data["instrument_id"].iloc[position - 1]),
                    "new_instrument_id": int(data["instrument_id"].iloc[position]),
                    "excluded_session": None,
                }
            )

    data = data.between_time("09:30", "16:00", inclusive="left")
    data = data[data.index.dayofweek < 5]
    if excluded_condition_dates:
        data = data[~pd.Index(data.index.date.astype(str)).isin(excluded_condition_dates)]

    roll_sessions: set[str] = set()
    if transitions and not data.empty:
        session_last_bar = pd.Series(data.index, index=data.index).groupby(data.index.date).max()
        for transition in transitions:
            transition_ts = pd.Timestamp(transition["timestamp"])
            affected = session_last_bar[session_last_bar >= transition_ts]
            if not affected.empty:
                session = affected.index[0].isoformat()
                transition["excluded_session"] = session
                roll_sessions.add(session)
    if roll_sessions:
        data = data[~pd.Index(data.index.date.astype(str)).isin(roll_sessions)]

    required = ["open", "high", "low", "close", "volume"]
    missing = [column for column in required if column not in data.columns]
    if missing:
        raise ValueError(f"Databento frame missing columns: {missing}")
    for column in ("open", "high", "low", "close"):
        data[column] = pd.to_numeric(data[column], errors="raise").astype(float)
    data["volume"] = pd.to_numeric(data["volume"], errors="raise").astype(int)
    if ((data["high"] < data[["open", "close", "low"]].max(axis=1)) | (data["low"] > data[["open", "close", "high"]].min(axis=1))).any():
        raise ValueError("Invalid OHLC relationship in Databento bars")

    keep = required + [column for column in ("instrument_id", "symbol") if column in data.columns]
    output = data[keep].copy()
    output.insert(0, "timestamp", output.index.tz_localize(None).map(lambda value: value.isoformat()))
    output.reset_index(drop=True, inplace=True)
    return output, sorted(roll_sessions), transitions


def expected_session_bars(
    first_date: str,
    last_date: str,
    *,
    calendar_name: str = "CME Globex Equity",
) -> dict[str, int]:
    """Expected 09:30-16:00 ET bar count per session from an exchange calendar."""
    import pandas_market_calendars as mcal

    calendar = mcal.get_calendar(calendar_name)
    schedule = calendar.schedule(start_date=first_date, end_date=last_date)
    expected: dict[str, int] = {}
    for session, row in schedule.iterrows():
        day = session.date()
        rth_start = pd.Timestamp(day, tz=NY) + pd.Timedelta(hours=9, minutes=30)
        rth_end = pd.Timestamp(day, tz=NY) + pd.Timedelta(hours=16)
        start = max(row["market_open"].tz_convert(NY), rth_start)
        end = min(row["market_close"].tz_convert(NY), rth_end)
        minutes = int((end - start) / pd.Timedelta(minutes=1))
        if minutes > 0:
            expected[day.isoformat()] = minutes
    return expected


def audit_sessions(
    clean: pd.DataFrame,
    *,
    expected_bars: dict[str, int],
    max_missing_bars: int = 5,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Report per-session missing bars and drop unexplained incomplete sessions."""
    session_dates = pd.to_datetime(clean["timestamp"]).dt.date.astype(str)
    counts = session_dates.value_counts().sort_index()
    incomplete_kept: list[dict[str, object]] = []
    excluded: list[dict[str, object]] = []
    for date, actual in counts.items():
        expected = expected_bars.get(date)
        if expected is None:
            excluded.append({"date": date, "bars": int(actual), "expected": None, "reason": "not_in_exchange_calendar"})
            continue
        if actual > expected:
            raise ValueError(f"Session {date} has {actual} bars but calendar expects {expected}")
        missing = expected - int(actual)
        if missing == 0:
            continue
        record = {"date": date, "bars": int(actual), "expected": expected, "missing": missing}
        if missing > max_missing_bars:
            excluded.append({**record, "reason": "incomplete_session"})
        else:
            incomplete_kept.append(record)
    excluded_dates = {row["date"] for row in excluded}
    if excluded_dates:
        clean = clean[~session_dates.isin(excluded_dates)].reset_index(drop=True)
    report = {
        "max_missing_bars": max_missing_bars,
        "sessions_audited": int(counts.size),
        "sessions_excluded": sorted(excluded, key=lambda row: row["date"]),
        "incomplete_sessions_kept": incomplete_kept,
    }
    return clean, report


def estimate_cost(client: object, spec: DownloadSpec) -> float:
    return float(client.metadata.get_cost(**request_kwargs(spec)))


def dataset_condition_exclusions(client: object, spec: DownloadSpec) -> dict[str, str]:
    conditions = client.metadata.get_dataset_condition(
        dataset=DATASET,
        start_date=spec.start,
        end_date=spec.end,
    )
    return {
        str(row["date"]): str(row["condition"])
        for row in conditions
        if row.get("condition") != "available"
    }


def fetch_one(
    client: object,
    spec: DownloadSpec,
    *,
    cache_dir: Path,
    output_dir: Path,
    calendar_name: str = "CME Globex Equity",
    max_missing_bars: int = 5,
) -> dict[str, object]:
    slug = f"{spec.product.lower()}_v0_1m_{spec.start}_{spec.end}".replace(":", "-")
    cache_path = cache_dir / f"{slug}.dbn.zst"
    csv_path = output_dir / f"{slug}_rth.csv"
    cache_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_reused = cache_path.exists()
    if cache_reused:
        import databento as db

        store = db.DBNStore.from_file(cache_path)
    else:
        store = client.timeseries.get_range(**request_kwargs(spec), path=cache_path)
    condition_exclusions = dataset_condition_exclusions(client, spec)
    clean, roll_sessions, roll_transitions = normalize_rth(
        store.to_df(),
        excluded_condition_dates=set(condition_exclusions),
    )
    first_date = clean["timestamp"].iloc[0][:10]
    last_date = clean["timestamp"].iloc[-1][:10]
    expected = expected_session_bars(first_date, last_date, calendar_name=calendar_name)
    clean, session_audit = audit_sessions(
        clean,
        expected_bars=expected,
        max_missing_bars=max_missing_bars,
    )
    clean.to_csv(csv_path, index=False)
    return {
        "spec": asdict(spec),
        "symbol": spec.symbol,
        "cache": str(cache_path),
        "cache_reused": cache_reused,
        "csv": str(csv_path),
        "rows": len(clean),
        "sessions": int(pd.to_datetime(clean["timestamp"]).dt.date.nunique()),
        "first_bar": clean["timestamp"].iloc[0],
        "last_bar": clean["timestamp"].iloc[-1],
        "roll_sessions_excluded": roll_sessions,
        "roll_transitions": roll_transitions,
        "session_audit": session_audit,
        "dataset_condition_dates_excluded": condition_exclusions,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--products", default="MES,ES")
    parser.add_argument("--start", default="2022-01-01")
    parser.add_argument("--end", default="2026-07-19")
    parser.add_argument("--download", action="store_true", help="Download only after displaying and checking cost")
    parser.add_argument("--max-cost", type=float, default=5.0)
    parser.add_argument("--cache-dir", type=Path, default=ROOT / "data" / "databento")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "examples")
    parser.add_argument("--manifest", type=Path, default=ROOT / "data" / "databento_futures_manifest.json")
    parser.add_argument("--calendar", default="CME Globex Equity", help="pandas_market_calendars calendar for session audit")
    parser.add_argument("--max-missing-bars", type=int, default=5, help="Missing 1m bars tolerated before a session is excluded")
    args = parser.parse_args()

    import databento as db

    client = db.Historical(_load_api_key())
    specs = [DownloadSpec(product.strip().upper(), args.start, args.end) for product in args.products.split(",") if product.strip()]
    estimates = [{"symbol": spec.symbol, "cost_usd": estimate_cost(client, spec)} for spec in specs]
    total = sum(row["cost_usd"] for row in estimates)
    preview = {"mode": "estimate", "dataset": DATASET, "schema": SCHEMA, "estimates": estimates, "total_cost_usd": total}
    print(json.dumps(preview, indent=2))
    if not args.download:
        print("Estimate only. Re-run with --download after reviewing the amount.")
        return
    if total > args.max_cost:
        raise RuntimeError(f"Estimated cost ${total:.2f} exceeds --max-cost ${args.max_cost:.2f}")

    results = [
        fetch_one(
            client,
            spec,
            cache_dir=args.cache_dir,
            output_dir=args.output_dir,
            calendar_name=args.calendar,
            max_missing_bars=args.max_missing_bars,
        )
        for spec in specs
    ]
    manifest = {**preview, "mode": "downloaded", "results": results}
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
