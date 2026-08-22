"""Point-in-time failed-breakout proxy scanner for liquidity-sweep research.

The retail term "liquidity sweep" is not an observable order type. This module
records a reproducible candle proxy: price breaches a pre-session reference,
closes back inside, and confirms the reversal within a fixed number of bars.
It is research-only and never has order, sizing, or strategy-veto authority.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import yfinance as yf
except ImportError:
    yf = None  # type: ignore[assignment]

ET = ZoneInfo("America/New_York")
UTC = timezone.utc

LOG_DIR = Path.home() / ".vibe-trading" / "logs"
DEFAULT_LEDGER = ROOT / "data" / "liquidity_sweep_ledger.jsonl"
DEFAULT_OUT = ROOT / "data" / "liquidity_sweep_context.json"

SWEEP_WINDOW_START_ET = time(9, 35)
SWEEP_WINDOW_END_ET = time(10, 30)
VOLUME_RATIO_MIN = float(os.getenv("SWEEP_VOL_RATIO", "1.2"))
SWEEP_EXCESS_MIN_PCT = float(os.getenv("SWEEP_EXCESS_MIN_PCT", "0.0003"))
SWEEP_EXCESS_MAX_PCT = float(os.getenv("SWEEP_EXCESS_MAX_PCT", "0.0030"))
CONFIRMATION_BARS = int(os.getenv("SWEEP_CONFIRMATION_BARS", "3"))
OUTCOME_HORIZONS = (5, 15, 30, 60)

PROXY_LABEL = "failed_breakout_wick_reclaim"
VOLUME_METHOD = "prior_bar_rolling_median_20"
DATA_SOURCE = "yfinance_ohlcv_1m_research_proxy"

LOG_DIR.mkdir(parents=True, exist_ok=True)
logger = logging.getLogger("liquidity_sweep_scanner")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handler = logging.StreamHandler()
    handler.setFormatter(fmt)
    logger.addHandler(handler)
    if not os.getenv("PYTEST_CURRENT_TEST"):
        from logging.handlers import RotatingFileHandler

        file_handler = RotatingFileHandler(
            LOG_DIR / "liquidity-sweep-scanner.log",
            maxBytes=20 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)


@dataclass(frozen=True)
class SweepEvent:
    schema_version: int
    event_id: str
    symbol: str
    session_date: str
    event_at: str
    available_at: str
    direction: str
    level: str
    level_price: float
    extreme_price: float
    sweep_excess_pct: float
    close_price: float
    confirmation_close: float
    volume_ratio: float
    confirmed: bool
    confirmation_bars: int
    proxy_label: str
    volume_method: str
    data_source: str
    point_in_time: bool
    forward_returns_bps: dict[str, float | None]
    mfe_bps_60m: float | None
    mae_bps_60m: float | None


def _iso_timestamp(value: Any) -> str:
    timestamp = value.to_pydatetime() if hasattr(value, "to_pydatetime") else value
    if not isinstance(timestamp, datetime):
        raise TypeError("bar index must contain datetime values")
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=ET)
    return timestamp.astimezone(UTC).isoformat()


def _event_id(symbol: str, event_at: str, direction: str, level: str) -> str:
    raw = f"{symbol}|{event_at}|{direction}|{level}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _session_bars(bars: Any, session_date: date) -> Any:
    if bars is None or getattr(bars, "empty", True):
        return bars
    result = bars.copy()
    if result.index.tz is None:
        result.index = result.index.tz_localize(ET)
    else:
        result.index = result.index.tz_convert(ET)
    return result[result.index.date == session_date]


def _prior_day_levels(symbol: str, *, session_date: date) -> dict[str, float]:
    if yf is None:
        raise RuntimeError("yfinance_unavailable")
    history = yf.Ticker(symbol).history(period="10d", interval="1d", auto_adjust=False)
    if history is None or history.empty:
        raise RuntimeError("daily_history_unavailable")
    candidates: list[tuple[date, Any]] = []
    for index, row in history.iterrows():
        timestamp = index.to_pydatetime() if hasattr(index, "to_pydatetime") else index
        row_date = timestamp.date()
        if row_date < session_date:
            candidates.append((row_date, row))
    if not candidates:
        raise RuntimeError("prior_session_unavailable")
    _, previous = max(candidates, key=lambda item: item[0])
    return {"PDH": float(previous["High"]), "PDL": float(previous["Low"])}


def _intraday_bars(symbol: str) -> Any:
    if yf is None:
        raise RuntimeError("yfinance_unavailable")
    bars = yf.Ticker(symbol).history(
        period="5d", interval="1m", prepost=True, auto_adjust=False
    )
    if bars is None or bars.empty:
        raise RuntimeError("intraday_history_unavailable")
    return bars


def _overnight_levels(session: Any) -> dict[str, float]:
    if session is None or getattr(session, "empty", True):
        return {}
    overnight = session[
        (session.index.time >= time(4, 0)) & (session.index.time < time(9, 30))
    ]
    if overnight.empty:
        return {}
    return {"ONH": float(overnight["High"].max()), "ONL": float(overnight["Low"].min())}


def _directional_bps(entry: float, exit_price: float, direction: str) -> float:
    sign = 1.0 if direction == "bullish" else -1.0
    return round(sign * (exit_price / entry - 1.0) * 10_000.0, 3)


def _outcomes(
    bar_rows: list[tuple[Any, Any]],
    confirmation_index: int,
    confirmation_close: float,
    direction: str,
) -> tuple[dict[str, float | None], float | None, float | None]:
    returns: dict[str, float | None] = {}
    for horizon in OUTCOME_HORIZONS:
        future_index = confirmation_index + horizon
        future_close = (
            _number(bar_rows[future_index][1].get("Close"))
            if future_index < len(bar_rows)
            else None
        )
        returns[f"{horizon}m"] = (
            _directional_bps(confirmation_close, future_close, direction)
            if future_close is not None
            else None
        )

    end_index = min(len(bar_rows), confirmation_index + 61)
    future = [row for _, row in bar_rows[confirmation_index + 1:end_index]]
    if not future:
        return returns, None, None
    highs = [_number(row.get("High")) for row in future]
    lows = [_number(row.get("Low")) for row in future]
    valid_highs = [value for value in highs if value is not None]
    valid_lows = [value for value in lows if value is not None]
    if not valid_highs or not valid_lows:
        return returns, None, None
    if direction == "bullish":
        mfe = _directional_bps(confirmation_close, max(valid_highs), direction)
        mae = _directional_bps(confirmation_close, min(valid_lows), direction)
    else:
        mfe = _directional_bps(confirmation_close, min(valid_lows), direction)
        mae = _directional_bps(confirmation_close, max(valid_highs), direction)
    return returns, max(0.0, mfe), min(0.0, mae)


def detect_sweeps(
    bars: Any,
    *,
    symbol: str,
    session_date: date,
    levels: dict[str, float],
    as_of: datetime | None = None,
) -> list[SweepEvent]:
    """Detect confirmed events using only bars available at ``as_of``."""
    session = _session_bars(bars, session_date)
    if session is None or getattr(session, "empty", True):
        return []
    if as_of is not None:
        cutoff = as_of.astimezone(ET)
        session = session[session.index <= cutoff]
    if session.empty:
        return []

    session = session.copy()
    baseline = session["Volume"].shift(1).rolling(20, min_periods=5).median()
    session["volume_ratio"] = session["Volume"] / baseline.replace(0, float("nan"))
    rows = list(session.iterrows())
    events: list[SweepEvent] = []

    for index, (timestamp, bar) in enumerate(rows):
        bar_time = timestamp.time().replace(tzinfo=None)
        if not (SWEEP_WINDOW_START_ET <= bar_time <= SWEEP_WINDOW_END_ET):
            continue
        volume_ratio = _number(bar.get("volume_ratio"))
        if volume_ratio is None or volume_ratio < VOLUME_RATIO_MIN:
            continue
        low = _number(bar.get("Low"))
        high = _number(bar.get("High"))
        close = _number(bar.get("Close"))
        if low is None or high is None or close is None:
            continue

        candidates: list[tuple[str, str, float, float]] = []
        for level_name, level_price in levels.items():
            if level_name.endswith("L") and low < level_price < close:
                candidates.append(("bullish", level_name, level_price, low))
            if level_name.endswith("H") and high > level_price > close:
                candidates.append(("bearish", level_name, level_price, high))

        for direction, level_name, level_price, extreme in candidates:
            excess = abs(extreme - level_price) / level_price
            if not SWEEP_EXCESS_MIN_PCT <= excess <= SWEEP_EXCESS_MAX_PCT:
                continue
            confirmation_index = None
            for offset in range(1, CONFIRMATION_BARS + 1):
                candidate_index = index + offset
                if candidate_index >= len(rows):
                    break
                confirmation_close = _number(rows[candidate_index][1].get("Close"))
                if confirmation_close is None:
                    continue
                confirmed = (
                    confirmation_close > close
                    if direction == "bullish"
                    else confirmation_close < close
                )
                if confirmed:
                    confirmation_index = candidate_index
                    break
            if confirmation_index is None:
                continue

            confirmation_close = float(rows[confirmation_index][1]["Close"])
            event_at = _iso_timestamp(timestamp)
            available_at = _iso_timestamp(rows[confirmation_index][0])
            forward, mfe, mae = _outcomes(
                rows, confirmation_index, confirmation_close, direction
            )
            events.append(SweepEvent(
                schema_version=2,
                event_id=_event_id(symbol, event_at, direction, level_name),
                symbol=symbol,
                session_date=session_date.isoformat(),
                event_at=event_at,
                available_at=available_at,
                direction=direction,
                level=level_name,
                level_price=round(level_price, 4),
                extreme_price=round(extreme, 4),
                sweep_excess_pct=round(excess, 7),
                close_price=round(close, 4),
                confirmation_close=round(confirmation_close, 4),
                volume_ratio=round(volume_ratio, 4),
                confirmed=True,
                confirmation_bars=confirmation_index - index,
                proxy_label=PROXY_LABEL,
                volume_method=VOLUME_METHOD,
                data_source=DATA_SOURCE,
                point_in_time=True,
                forward_returns_bps=forward,
                mfe_bps_60m=mfe,
                mae_bps_60m=mae,
            ))
    return events


def scan_sweeps(
    symbol: str = "SPY",
    *,
    bars: Any | None = None,
    levels: dict[str, float] | None = None,
    as_of: datetime | None = None,
) -> list[SweepEvent]:
    now_et = (as_of or datetime.now(tz=ET)).astimezone(ET)
    intraday = bars if bars is not None else _intraday_bars(symbol)
    session = _session_bars(intraday, now_et.date())
    reference_levels = dict(levels or _prior_day_levels(symbol, session_date=now_et.date()))
    reference_levels.update(_overnight_levels(session))
    return detect_sweeps(
        intraday,
        symbol=symbol,
        session_date=now_et.date(),
        levels=reference_levels,
        as_of=now_et,
    )


def research_context(
    symbol: str = "SPY",
    *,
    events: Iterable[SweepEvent] | None = None,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """Return point-in-time telemetry with explicitly zero execution authority."""
    generated_at = (as_of or datetime.now(tz=UTC)).astimezone(UTC).isoformat()
    try:
        observed = list(events) if events is not None else scan_sweeps(symbol, as_of=as_of)
        status = "available"
        reason = "confirmed_proxy_events_observed" if observed else "no_confirmed_proxy_event"
    except Exception as exc:
        observed = []
        status = "unavailable"
        reason = f"scanner_error:{type(exc).__name__}"
    return {
        "schema_version": 2,
        "symbol": symbol,
        "generated_at": generated_at,
        "status": status,
        "reason": reason,
        "proxy_label": PROXY_LABEL,
        "data_source": DATA_SOURCE,
        "event_count": len(observed),
        "events": [asdict(event) for event in observed],
        "promotion_status": "research_only",
        "execution_authority": False,
        "can_submit_orders": False,
        "veto": False,
        "note": "OHLCV proxy cannot identify resting stops or institutional intent.",
    }


def latest_research_context(
    symbol: str = "SPY",
    *,
    path: Path = DEFAULT_OUT,
    as_of: datetime | None = None,
    max_age_minutes: int = 180,
) -> dict[str, Any]:
    """Read fresh telemetry without adding network I/O to a strategy entry."""
    now = (as_of or datetime.now(tz=UTC)).astimezone(UTC)
    unavailable = research_context(symbol, events=[], as_of=now)
    unavailable.update({"status": "unavailable", "reason": "cached_context_unavailable"})
    if not path.exists():
        return unavailable
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        context = payload.get("research_context")
        generated_at = datetime.fromisoformat(
            str(payload.get("generated_at")).replace("Z", "+00:00")
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        unavailable["reason"] = "cached_context_invalid"
        return unavailable
    if not isinstance(context, dict) or str(context.get("symbol")) != symbol:
        unavailable["reason"] = "cached_context_symbol_mismatch"
        return unavailable
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=UTC)
    generated_at = generated_at.astimezone(UTC)
    age_minutes = (now - generated_at).total_seconds() / 60.0
    session_date = str(payload.get("session_date") or "")
    if age_minutes < 0:
        unavailable["reason"] = "cached_context_from_future"
        return unavailable
    if age_minutes > max_age_minutes or session_date != now.astimezone(ET).date().isoformat():
        unavailable["reason"] = "cached_context_stale"
        return unavailable
    result = dict(context)
    result["cache_age_minutes"] = round(age_minutes, 2)
    result["cache_source"] = str(path)
    return result


def condor_veto_context(symbol: str = "SPY") -> dict[str, Any]:
    """Compatibility wrapper. Sweeps cannot veto the condor before validation."""
    return research_context(symbol)


def _upsert_ledger(path: Path, events: Iterable[SweepEvent]) -> int:
    records: dict[str, dict[str, Any]] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            event_id = str(record.get("event_id") or "")
            if not event_id:
                legacy_key = json.dumps(record, separators=(",", ":"), sort_keys=True)
                event_id = "legacy-" + hashlib.sha256(legacy_key.encode("utf-8")).hexdigest()[:17]
                record["event_id"] = event_id
            records[event_id] = record
    before = set(records)
    for event in events:
        records[event.event_id] = asdict(event)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    payload = "".join(
        json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n"
        for record in sorted(records.values(), key=lambda item: (item["event_at"], item["event_id"]))
    )
    temp.write_text(payload, encoding="utf-8")
    temp.replace(path)
    return len(set(records) - before)


def _load_v2_events(path: Path) -> list[SweepEvent]:
    if not path.exists():
        return []
    valid_fields = set(SweepEvent.__dataclass_fields__)
    events: list[SweepEvent] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("schema_version") != 2 or not valid_fields.issubset(record):
            continue
        try:
            events.append(SweepEvent(**{key: record[key] for key in valid_fields}))
        except (TypeError, ValueError):
            continue
    return events


def evaluate_events(events: Iterable[SweepEvent]) -> dict[str, Any]:
    observed = list(events)
    sessions = {event.session_date for event in observed}
    metrics: dict[str, Any] = {}
    for horizon in OUTCOME_HORIZONS:
        key = f"{horizon}m"
        values = [
            event.forward_returns_bps[key]
            for event in observed
            if event.forward_returns_bps.get(key) is not None
        ]
        metrics[key] = {
            "labeled_n": len(values),
            "positive_rate": round(sum(value > 0 for value in values) / len(values), 4)
            if values else None,
            "mean_directional_bps": round(sum(values) / len(values), 3) if values else None,
        }
    enough_for_backtest = len(observed) >= 100 and len(sessions) >= 60
    return {
        "event_count": len(observed),
        "session_count": len(sessions),
        "horizons": metrics,
        "eligible_for_strategy_backtest": enough_for_backtest,
        "execution_promotion_allowed": False,
        "promotion_requirements": {
            "minimum_events": 100,
            "minimum_sessions": 60,
            "then_required": "separate_walk_forward_option_backtest_net_of_spread_and_fees",
        },
    }


def run_scanner(
    ledger: Path = DEFAULT_LEDGER,
    out: Path = DEFAULT_OUT,
    *,
    symbol: str = "SPY",
    as_of: datetime | None = None,
) -> dict[str, Any]:
    events = scan_sweeps(symbol, as_of=as_of)
    new_events = _upsert_ledger(ledger, events)
    all_events = _load_v2_events(ledger)
    generated_at = (as_of or datetime.now(tz=UTC)).astimezone(UTC)
    result = {
        "schema_version": 2,
        "session_date": generated_at.astimezone(ET).date().isoformat(),
        "generated_at": generated_at.isoformat(),
        "symbol": symbol,
        "events": [asdict(event) for event in events],
        "new_event_count": new_events,
        "evaluation": evaluate_events(all_events),
        "research_context": research_context(symbol, events=events, as_of=as_of),
        "observation_mode": True,
        "execution_enabled": False,
        "can_submit_orders": False,
        "orders_submitted": 0,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    logger.info("Sweep proxy scan complete: %d events, %d new", len(events), new_events)
    return result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Liquidity sweep research scanner")
    parser.add_argument("--symbol", default="SPY")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--veto-check", action="store_true")
    args = parser.parse_args()

    if args.veto_check:
        print(json.dumps(condor_veto_context(args.symbol), indent=2))
        return
    print(json.dumps(
        run_scanner(ledger=args.ledger, out=args.out, symbol=args.symbol), indent=2
    ))


if __name__ == "__main__":
    main()
