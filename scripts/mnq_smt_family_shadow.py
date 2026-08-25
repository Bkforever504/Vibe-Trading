#!/usr/bin/env python3
"""Shared deterministic shadow engine for the frozen MNQ SMT experiment family.

This module has no broker imports or order authority.  It uses completed proxy
OHLCV bars, emits append-only JSONL events, and keeps every candidate
promotion-ineligible until the frozen evidence blockers are removed in a new
preregistration.
"""
from __future__ import annotations

import hashlib
import json
import math
import warnings
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
ET = ZoneInfo("America/New_York")
FAMILY_ID = "mnq-smt-cisd-family"
UNIVERSE_PATH = ROOT / "data" / "universes" / "mnq_smt_family_2026-08-24.json"
UNIVERSE_HASH = "sha256:84d8ceaebd9f55d346059aba4809f8389fbe26099cd7878b0498c12dcd11ddbe"
EXPECTED_SYMBOLS = ("ES", "MES", "MNQ", "NQ")

DATA_SOURCE = "yfinance_proxy_MNQ=NQ=MES=ES_completed_5m_1h_ohlcv"
EVIDENCE_TIER = "proxy_ohlcv_non_executable"
POINT_VALUE = 2.0
TICK_SIZE = 0.25
COMMISSION_PER_SIDE = 0.35
SLIPPAGE_TICKS_PER_SIDE = 1
FRICTION_ROUND_TRIP = 2 * (COMMISSION_PER_SIDE + SLIPPAGE_TICKS_PER_SIDE * TICK_SIZE * POINT_VALUE)
TIME_EXIT = time(16, 30)  # 30 minutes before the 17:00 ET equity-index maintenance close.
RTH_START = time(9, 30)
RTH_END = time(16, 0)
SMT_MAGNITUDE_MIN = 0.0015
RVOL_MIN = 1.2
VOLUME_LOOKBACK = 20
PIVOT_SIDE_BARS = 2


@dataclass(frozen=True)
class StrategyConfig:
    strategy_id: str
    spec_hash: str
    spec_path: str
    log_path: Path
    detector: str
    evidence_blockers: tuple[str, ...]


COMMON_BLOCKERS = (
    "databento_mbo_required",
    "executable_futures_bbo_required",
    "kenny_signoff_required",
)


STRATEGY_CONFIGS: dict[str, StrategyConfig] = {
    "mnq-smt-cisd-fvg-v1": StrategyConfig(
        strategy_id="mnq-smt-cisd-fvg-v1",
        spec_hash="sha256:686aed721b83bc2e0c0051adc2af863f2eeee459874c8f13d275489c56b7bb2d",
        spec_path="research/preregistrations/mnq_smt_cisd_fvg_v1.md",
        log_path=ROOT / "data" / "mnq_smt_cisd_fvg_v1_shadow_log.jsonl",
        detector="composite",
        evidence_blockers=COMMON_BLOCKERS + ("out_of_sample_holdout_pass_required",),
    ),
    "mnq-pdl-rejection-v1": StrategyConfig(
        strategy_id="mnq-pdl-rejection-v1",
        spec_hash="sha256:54cb3221c4fabdc9d04cf85ca9dcdf3f041883fab230feb113936969ca3732ba",
        spec_path="research/preregistrations/mnq_pdl_rejection_v1.md",
        log_path=ROOT / "data" / "mnq_pdl_rejection_v1_shadow_log.jsonl",
        detector="pdl_rejection",
        evidence_blockers=COMMON_BLOCKERS,
    ),
    "mnq-smt-only-v1": StrategyConfig(
        strategy_id="mnq-smt-only-v1",
        spec_hash="sha256:b2680f71689b392dda80a1ffd5a1a5bac4453edee8e1e4e5801a01d6fca12bd0",
        spec_path="research/preregistrations/mnq_smt_only_v1.md",
        log_path=ROOT / "data" / "mnq_smt_only_v1_shadow_log.jsonl",
        detector="smt_only",
        evidence_blockers=COMMON_BLOCKERS,
    ),
    "mnq-cisd-only-v1": StrategyConfig(
        strategy_id="mnq-cisd-only-v1",
        spec_hash="sha256:b55a94d9663662eb59d18a6eb23af8808ac752bb015fb676005d716680719b4a",
        spec_path="research/preregistrations/mnq_cisd_only_v1.md",
        log_path=ROOT / "data" / "mnq_cisd_only_v1_shadow_log.jsonl",
        detector="cisd_only",
        evidence_blockers=COMMON_BLOCKERS,
    ),
}


def utc_z(value: datetime | None = None) -> str:
    return (value or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _flatten(frame: Any) -> Any:
    import pandas as pd

    if isinstance(frame.columns, pd.MultiIndex):
        frame = frame.copy()
        frame.columns = frame.columns.get_level_values(0)
    return frame


def to_et(frame: Any) -> Any:
    import pandas as pd

    frame = _flatten(frame).sort_index()
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise TypeError("market data must use a DatetimeIndex")
    if frame.index.tz is None:
        frame.index = frame.index.tz_localize(ET)
    else:
        frame.index = frame.index.tz_convert(ET)
    return frame


def completed_bars(frame: Any, *, as_of: datetime, interval: timedelta) -> Any:
    """Return only bars whose full interval existed at the decision timestamp."""
    normalized = to_et(frame)
    cutoff = as_of.astimezone(ET)
    return normalized[(normalized.index + interval) <= cutoff]


def session_rows(frame: Any, session_date: date) -> Any:
    normalized = to_et(frame)
    return normalized[normalized.index.date == session_date].between_time("09:30", "15:59")


def prior_day_levels(frame: Any, session_date: date) -> dict[str, Any]:
    normalized = to_et(frame)
    dates = sorted({stamp.date() for stamp in normalized.index if stamp.date() < session_date})
    if not dates:
        raise ValueError("prior RTH session unavailable")
    # Futures data includes Sunday evening bars stamped with Sunday's date.
    # Walk backward to the latest actual RTH session instead of treating that
    # overnight-only calendar date as the prior cash session.
    for prior_date in reversed(dates):
        rows = session_rows(normalized, prior_date)
        if not rows.empty:
            return {
                "session_date": prior_date.isoformat(),
                "pdh": float(rows["High"].max()),
                "pdl": float(rows["Low"].min()),
            }
    raise ValueError("prior RTH high/low unavailable")


def _load_universe(path: Path = UNIVERSE_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    symbols = tuple(sorted({str(value).upper() for value in payload.get("symbols", [])}))
    canonical = "".join(f"{symbol}\n" for symbol in symbols)
    actual_hash = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if symbols != EXPECTED_SYMBOLS:
        raise ValueError("MNQ SMT universe membership differs from frozen symbols")
    if actual_hash != UNIVERSE_HASH or payload.get("sha256_membership_hash") != UNIVERSE_HASH:
        raise ValueError("MNQ SMT universe hash mismatch")
    return payload


def _download(symbol: str, *, period: str, interval: str) -> Any:
    import yfinance as yf

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return yf.download(
            symbol,
            period=period,
            interval=interval,
            auto_adjust=False,
            prepost=True,
            progress=False,
        )


def download_family_data() -> dict[str, Any]:
    """Load every frozen member; ES is the primary SMT comparator, MES fallback."""
    return {
        "mnq_5m": _download("MNQ=F", period="10d", interval="5m"),
        "mnq_1h": _download("MNQ=F", period="60d", interval="60m"),
        "nq_1h": _download("NQ=F", period="60d", interval="60m"),
        "mes_1h": _download("MES=F", period="60d", interval="60m"),
        "es_1h": _download("ES=F", period="60d", interval="60m"),
    }


def _context_h1(data: Mapping[str, Any]) -> tuple[Any, str]:
    es = data.get("es_1h")
    if es is not None and not es.empty:
        return es, "ES=F"
    mes = data.get("mes_1h")
    if mes is not None and not mes.empty:
        return mes, "MES=F"
    raise ValueError("ES/MES context H1 bars unavailable")


def _pivot_levels(rows: Any, before_position: int) -> tuple[tuple[float, str] | None, tuple[float, str] | None]:
    """Latest pivots confirmed by two bars on the right before a candidate bar."""
    last_high: tuple[float, str] | None = None
    last_low: tuple[float, str] | None = None
    for index in range(PIVOT_SIDE_BARS, max(PIVOT_SIDE_BARS, before_position - PIVOT_SIDE_BARS)):
        center = rows.iloc[index]
        left = rows.iloc[index - PIVOT_SIDE_BARS:index]
        right = rows.iloc[index + 1:index + 1 + PIVOT_SIDE_BARS]
        if len(right) != PIVOT_SIDE_BARS:
            continue
        stamp = rows.index[index].isoformat()
        high = float(center["High"])
        low = float(center["Low"])
        if high > float(left["High"].max()) and high >= float(right["High"].max()):
            last_high = (high, stamp)
        if low < float(left["Low"].min()) and low <= float(right["Low"].min()):
            last_low = (low, stamp)
    return last_high, last_low


def _return(row: Mapping[str, Any]) -> float:
    opened = float(row["Open"])
    if opened == 0:
        raise ValueError("zero open prevents return normalization")
    return float(row["Close"]) / opened - 1.0


def _aligned_row(frame: Any, timestamp: Any) -> Any | None:
    normalized = to_et(frame)
    if timestamp in normalized.index:
        return normalized.loc[timestamp]
    candidates = normalized[abs(normalized.index - timestamp) <= timedelta(minutes=2)]
    return None if candidates.empty else candidates.iloc[-1]


def _plan(direction: str, entry: float, stop: float, *, actionable_at: datetime, trigger: dict[str, Any]) -> dict[str, Any]:
    risk = (entry - stop) if direction == "long" else (stop - entry)
    if risk <= 0:
        raise ValueError("non-positive stop distance")
    sign = 1.0 if direction == "long" else -1.0
    return {
        "symbol": "MNQ",
        "direction": direction,
        "entry_price": entry,
        "stop_price": stop,
        "t1_price": entry + sign * risk,
        "t2_price": entry + sign * 2.0 * risk,
        "stop_distance_pts": risk,
        "max_risk_per_contract": risk * POINT_VALUE,
        "risk_fraction": 0.005,
        "position_sizing_formula": "floor((equity*0.005)/(stop_distance_pts*2.0)) capped at 10",
        "max_contracts": 10,
        "quantity": 1,
        "actionable_at": actionable_at.isoformat(),
        "trigger": trigger,
    }


def detect_pdl_rejection(mnq_5m: Any, session_date: date) -> dict[str, Any]:
    levels = prior_day_levels(mnq_5m, session_date)
    rows = session_rows(mnq_5m, session_date)
    for position, (stamp, row) in enumerate(rows.iterrows()):
        if position < VOLUME_LOOKBACK:
            continue
        high, low, opened, close = (float(row[key]) for key in ("High", "Low", "Open", "Close"))
        bar_range = high - low
        if bar_range <= 0:
            continue
        average_volume = float(rows.iloc[position - VOLUME_LOOKBACK:position]["Volume"].astype(float).mean())
        volume = float(row["Volume"])
        rvol = volume / average_volume if average_volume > 0 else None
        direction: str | None = None
        level_name: str | None = None
        if low < levels["pdl"] and close > levels["pdl"] and (close - low) / bar_range >= 0.40:
            direction, level_name = "long", "PDL"
        elif high > levels["pdh"] and close < levels["pdh"] and (high - close) / bar_range >= 0.40:
            direction, level_name = "short", "PDH"
        if direction is None or rvol is None or rvol < RVOL_MIN:
            continue
        stop = low - TICK_SIZE if direction == "long" else high + TICK_SIZE
        trigger = {
            "pattern": "pdl_pdh_rejection",
            "level_name": level_name,
            "level_price": levels[level_name.lower()],
            "bar_timestamp": stamp.isoformat(),
            "reclaim_fraction": round((close - low) / bar_range if direction == "long" else (high - close) / bar_range, 6),
            "rvol_20": round(rvol, 6),
            "prior_session": levels["session_date"],
        }
        return {"should_enter": True, "reason": "eligible", "plan": _plan(direction, close, stop, actionable_at=stamp + timedelta(minutes=5), trigger=trigger)}
    return {"should_enter": False, "reason": "no_first_rth_pdl_pdh_rejection", "filters": {"prior_day_levels": levels}}


def _smt_candidates(mnq_h1: Any, context_h1: Any, session_date: date, *, require_prior_day_tag: bool) -> list[dict[str, Any]]:
    mnq_rows = session_rows(mnq_h1, session_date)
    context_rows = session_rows(context_h1, session_date)
    if mnq_rows.empty or context_rows.empty:
        return []
    mnq_levels = prior_day_levels(mnq_h1, session_date) if require_prior_day_tag else None
    context_levels = prior_day_levels(context_h1, session_date) if require_prior_day_tag else None
    output: list[dict[str, Any]] = []
    for position in range(len(mnq_rows)):
        stamp = mnq_rows.index[position]
        mnq_row = mnq_rows.iloc[position]
        context_row = _aligned_row(context_rows, stamp)
        if context_row is None:
            continue
        direction: str | None = None
        level_name: str | None = None
        if require_prior_day_tag:
            if float(mnq_row["Low"]) <= float(mnq_levels["pdl"]) and float(context_row["Low"]) > float(context_levels["pdl"]):
                direction, level_name = "long", "PDL"
            elif float(mnq_row["High"]) >= float(mnq_levels["pdh"]) and float(context_row["High"]) < float(context_levels["pdh"]):
                direction, level_name = "short", "PDH"
        elif position > 0:
            previous = mnq_rows.iloc[position - 1]
            previous_context = _aligned_row(context_rows, mnq_rows.index[position - 1])
            if previous_context is None:
                continue
            if float(mnq_row["Low"]) < float(previous["Low"]) and float(context_row["Low"]) >= float(previous_context["Low"]):
                direction = "long"
            elif float(mnq_row["High"]) > float(previous["High"]) and float(context_row["High"]) <= float(previous_context["High"]):
                direction = "short"
        if direction is None:
            continue
        magnitude = abs(_return(mnq_row) - _return(context_row))
        if magnitude < SMT_MAGNITUDE_MIN:
            continue
        output.append({
            "direction": direction,
            "level_name": level_name,
            "level_price": float(mnq_levels[level_name.lower()]) if mnq_levels and level_name else None,
            "bar_timestamp": stamp,
            "actionable_at": stamp + timedelta(hours=1),
            "magnitude": magnitude,
            "mnq_return": _return(mnq_row),
            "context_return": _return(context_row),
            "mnq_row": mnq_row,
            "context_row": context_row,
        })
    return output


def detect_smt_only(mnq_h1: Any, context_h1: Any, session_date: date, *, context_symbol: str = "ES=F") -> dict[str, Any]:
    candidates = _smt_candidates(mnq_h1, context_h1, session_date, require_prior_day_tag=False)
    if not candidates:
        return {"should_enter": False, "reason": "no_first_rth_smt_divergence"}
    signal = candidates[0]
    direction = signal["direction"]
    row = signal["mnq_row"]
    entry = float(row["Close"])
    stop = float(row["Low"]) - TICK_SIZE if direction == "long" else float(row["High"]) + TICK_SIZE
    trigger = {
        "pattern": "smt_only",
        "bar_timestamp": signal["bar_timestamp"].isoformat(),
        "smt_magnitude": round(signal["magnitude"], 8),
        "mnq_return": round(signal["mnq_return"], 8),
        "context_return": round(signal["context_return"], 8),
        "context_symbol": context_symbol,
    }
    return {"should_enter": True, "reason": "eligible", "plan": _plan(direction, entry, stop, actionable_at=signal["actionable_at"], trigger=trigger)}


def _cisd_candidates(rows: Any) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for position in range(max(VOLUME_LOOKBACK, 1), len(rows)):
        last_high, last_low = _pivot_levels(rows, position)
        if last_high is None or last_low is None:
            continue
        row = rows.iloc[position]
        previous = rows.iloc[position - 1]
        average_volume = float(rows.iloc[position - VOLUME_LOOKBACK:position]["Volume"].astype(float).mean())
        volume = float(row["Volume"])
        rvol = volume / average_volume if average_volume > 0 else None
        direction: str | None = None
        pivot: tuple[float, str] | None = None
        if float(row["Close"]) > last_high[0] and float(row["Low"]) < float(previous["Low"]):
            direction, pivot = "long", last_high
        elif float(row["Close"]) < last_low[0] and float(row["High"]) > float(previous["High"]):
            direction, pivot = "short", last_low
        if direction is not None:
            output.append({
                "direction": direction,
                "bar_timestamp": rows.index[position],
                "actionable_at": rows.index[position] + timedelta(minutes=5),
                "row": row,
                "position": position,
                "pivot_price": pivot[0],
                "pivot_timestamp": pivot[1],
                "rvol": rvol,
            })
    return output


def detect_cisd_only(mnq_5m: Any, session_date: date) -> dict[str, Any]:
    rows = session_rows(mnq_5m, session_date)
    for signal in _cisd_candidates(rows):
        if signal["rvol"] is None or signal["rvol"] < RVOL_MIN:
            continue
        direction = signal["direction"]
        row = signal["row"]
        entry = float(row["Close"])
        stop = float(row["Low"]) - TICK_SIZE if direction == "long" else float(row["High"]) + TICK_SIZE
        trigger = {
            "pattern": "cisd_only",
            "bar_timestamp": signal["bar_timestamp"].isoformat(),
            "pivot_price": signal["pivot_price"],
            "pivot_timestamp": signal["pivot_timestamp"],
            "rvol_20": round(float(signal["rvol"]), 6),
        }
        return {"should_enter": True, "reason": "eligible", "plan": _plan(direction, entry, stop, actionable_at=signal["actionable_at"], trigger=trigger)}
    return {"should_enter": False, "reason": "no_first_rth_volume_confirmed_cisd"}


def _fvg_zones(rows: Any, start_position: int, end_position: int, direction: str) -> list[dict[str, Any]]:
    zones: list[dict[str, Any]] = []
    for position in range(max(start_position + 2, 2), end_position + 1):
        first = rows.iloc[position - 2]
        third = rows.iloc[position]
        if direction == "long" and float(first["High"]) < float(third["Low"]):
            zones.append({"type": "fvg", "low": float(first["High"]), "high": float(third["Low"]), "formed_at": rows.index[position].isoformat()})
        elif direction == "short" and float(first["Low"]) > float(third["High"]):
            zones.append({"type": "fvg", "low": float(third["High"]), "high": float(first["Low"]), "formed_at": rows.index[position].isoformat()})
    return zones


def _order_block(rows: Any, start_position: int, end_position: int, direction: str) -> dict[str, Any] | None:
    for position in range(end_position - 1, start_position - 1, -1):
        row = rows.iloc[position]
        opposing = float(row["Close"]) < float(row["Open"]) if direction == "long" else float(row["Close"]) > float(row["Open"])
        if opposing:
            return {
                "type": "order_block",
                "low": float(row["Low"]),
                "high": float(row["High"]),
                "formed_at": rows.index[position].isoformat(),
            }
    return None


def _rejection(row: Mapping[str, Any], zone: Mapping[str, Any], direction: str) -> bool:
    high, low, opened, close = (float(row[key]) for key in ("High", "Low", "Open", "Close"))
    total = high - low
    if total <= 0 or high < float(zone["low"]) or low > float(zone["high"]):
        return False
    close_inside = float(zone["low"]) <= close <= float(zone["high"])
    if direction == "long":
        wick = min(opened, close) - low
        return close_inside and close > opened and wick / total >= 0.60
    wick = high - max(opened, close)
    return close_inside and close < opened and wick / total >= 0.60


def detect_composite(mnq_h1: Any, context_h1: Any, mnq_5m: Any, session_date: date, *, context_symbol: str = "ES=F") -> dict[str, Any]:
    h1_signals = _smt_candidates(mnq_h1, context_h1, session_date, require_prior_day_tag=True)
    rows = session_rows(mnq_5m, session_date)
    for smt in h1_signals:
        tag_actionable = smt["actionable_at"]
        deadline = tag_actionable + timedelta(hours=2)
        start_positions = [index for index, stamp in enumerate(rows.index) if stamp >= tag_actionable]
        if not start_positions:
            continue
        leg_start = start_positions[0]
        cisd: dict[str, Any] | None = None
        for candidate in _cisd_candidates(rows):
            if candidate["direction"] != smt["direction"]:
                continue
            if not (tag_actionable <= candidate["actionable_at"] <= deadline):
                continue
            close = float(candidate["row"]["Close"])
            crossed_tag = close > float(smt["level_price"]) if smt["direction"] == "long" else close < float(smt["level_price"])
            if crossed_tag:
                cisd = candidate
                break
        if cisd is None:
            continue
        cisd_position = int(cisd["position"])
        zones = _fvg_zones(rows, leg_start, cisd_position, smt["direction"])
        order_block = _order_block(rows, leg_start, cisd_position, smt["direction"])
        if order_block:
            zones.append(order_block)
        if not zones:
            continue
        for position in range(cisd_position + 1, len(rows)):
            stamp = rows.index[position]
            if stamp < cisd["actionable_at"]:
                continue
            row = rows.iloc[position]
            qualifying = [zone for zone in zones if _rejection(row, zone, smt["direction"])]
            if not qualifying:
                continue
            entry = float(row["Close"])
            if smt["direction"] == "long":
                viable = [zone for zone in qualifying if float(zone["low"]) - TICK_SIZE < entry]
                if not viable:
                    continue
                zone = max(viable, key=lambda item: float(item["low"]))
                stop = float(zone["low"]) - TICK_SIZE
            else:
                viable = [zone for zone in qualifying if float(zone["high"]) + TICK_SIZE > entry]
                if not viable:
                    continue
                zone = min(viable, key=lambda item: float(item["high"]))
                stop = float(zone["high"]) + TICK_SIZE
            trigger = {
                "pattern": "smt_cisd_fvg_or_order_block_retrace",
                "prior_day_level": smt["level_name"],
                "level_price": smt["level_price"],
                "smt_bar_timestamp": smt["bar_timestamp"].isoformat(),
                "smt_actionable_at": smt["actionable_at"].isoformat(),
                "smt_magnitude": round(smt["magnitude"], 8),
                "context_symbol": context_symbol,
                "cisd_bar_timestamp": cisd["bar_timestamp"].isoformat(),
                "cisd_actionable_at": cisd["actionable_at"].isoformat(),
                "cisd_pivot_price": cisd["pivot_price"],
                "zone": zone,
                "rejection_bar_timestamp": stamp.isoformat(),
                "rejection_wick_minimum": 0.60,
            }
            return {"should_enter": True, "reason": "eligible", "plan": _plan(smt["direction"], entry, stop, actionable_at=stamp + timedelta(minutes=5), trigger=trigger)}
    return {"should_enter": False, "reason": "composite_sequence_incomplete"}


DETECTORS: dict[str, Callable[..., dict[str, Any]]] = {
    "pdl_rejection": detect_pdl_rejection,
    "smt_only": detect_smt_only,
    "cisd_only": detect_cisd_only,
    "composite": detect_composite,
}


def build_entry_plan(config: StrategyConfig, data: Mapping[str, Any], session_date: date) -> dict[str, Any]:
    if config.detector == "pdl_rejection":
        return detect_pdl_rejection(data["mnq_5m"], session_date)
    if config.detector == "cisd_only":
        return detect_cisd_only(data["mnq_5m"], session_date)
    context, context_symbol = _context_h1(data)
    if config.detector == "smt_only":
        return detect_smt_only(data["mnq_1h"], context, session_date, context_symbol=context_symbol)
    if config.detector == "composite":
        return detect_composite(data["mnq_1h"], context, data["mnq_5m"], session_date, context_symbol=context_symbol)
    raise ValueError(f"unknown detector {config.detector}")


def resolve_plan(mnq_5m: Any, plan: Mapping[str, Any], *, as_of: datetime | None = None) -> dict[str, Any] | None:
    rows = to_et(mnq_5m)
    actionable_at = datetime.fromisoformat(str(plan["actionable_at"])).astimezone(ET)
    session_date = actionable_at.date()
    end = datetime.combine(session_date, TIME_EXIT, ET)
    if as_of is not None:
        rows = completed_bars(rows, as_of=as_of, interval=timedelta(minutes=5))
    forward = rows[(rows.index >= actionable_at) & (rows.index < end)]
    if forward.empty:
        return None

    direction = str(plan["direction"])
    is_long = direction == "long"
    entry = float(plan["entry_price"])
    original_stop = float(plan["stop_price"])
    stop = original_stop
    t1 = float(plan["t1_price"])
    t2 = float(plan["t2_price"])
    risk = float(plan["stop_distance_pts"])
    t1_hit = False
    banked = 0.0
    remaining = 0.0
    exit_price: float | None = None
    exit_timestamp: datetime | None = None
    reason: str | None = None

    for stamp, row in forward.iterrows():
        high, low = float(row["High"]), float(row["Low"])
        stop_hit = low <= stop if is_long else high >= stop
        if stop_hit:  # adverse-first, including after the trail is active
            remaining = 0.5 * ((stop - entry) if is_long else (entry - stop)) if t1_hit else ((stop - entry) if is_long else (entry - stop))
            exit_price, exit_timestamp = stop, stamp
            reason = "trail_stop_after_t1" if t1_hit else "stop_before_t1"
            break
        if not t1_hit:
            target_hit = high >= t1 if is_long else low <= t1
            if target_hit:
                t1_hit = True
                banked = 0.5 * risk
                stop = entry + 0.25 * risk if is_long else entry - 0.25 * risk
                t2_same_bar = high >= t2 if is_long else low <= t2
                if t2_same_bar:
                    remaining = risk
                    exit_price, exit_timestamp, reason = t2, stamp, "t2_after_t1"
                    break
                continue
        else:
            target_hit = high >= t2 if is_long else low <= t2
            if target_hit:
                remaining = risk
                exit_price, exit_timestamp, reason = t2, stamp, "t2_after_t1"
                break

    if reason is None:
        enough_for_time_exit = (as_of is None and forward.index[-1] + timedelta(minutes=5) >= end) or (as_of is not None and as_of.astimezone(ET) >= end)
        if not enough_for_time_exit:
            return None
        final = forward.iloc[-1]
        exit_price = float(final["Close"])
        raw = (exit_price - entry) if is_long else (entry - exit_price)
        remaining = 0.5 * raw if t1_hit else raw
        exit_timestamp = forward.index[-1] + timedelta(minutes=5)
        reason = "time_exit_16_30_et"

    total_points = banked + remaining
    gross = total_points * POINT_VALUE
    net = gross - FRICTION_ROUND_TRIP
    return {
        "exit_reason": reason,
        "exit_timestamp": exit_timestamp.isoformat() if exit_timestamp else None,
        "exit_price_observed_proxy": exit_price,
        "t1_hit": t1_hit,
        "banked_half_points": round(banked, 6),
        "remaining_points": round(remaining, 6),
        "total_points": round(total_points, 6),
        "gross_dollar": round(gross, 2),
        "friction_round_trip_dollar": round(FRICTION_ROUND_TRIP, 2),
        "net_dollar": round(net, 2),
        "outcome": "win" if net > 0 else ("loss" if net < 0 else "flat"),
    }


def _records(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return []
    output: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            output.append(value)
    return output


def _append(record: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(dict(record), sort_keys=True, separators=(",", ":")) + "\n")


def _base(config: StrategyConfig, event_type: str, as_of: datetime) -> dict[str, Any]:
    universe = _load_universe()
    return {
        "schema_version": 1,
        "event_type": event_type,
        "type": event_type,
        "captured_at": utc_z(as_of),
        "timestamp": utc_z(as_of),
        "strategy_id": config.strategy_id,
        "candidate_id": config.strategy_id,
        "family_id": FAMILY_ID,
        "setup_family": FAMILY_ID,
        "preregistration": config.spec_path,
        "spec_hash": config.spec_hash,
        "universe_id": universe["universe_id"],
        "universe_version": universe["universe_version"],
        "universe_hash": UNIVERSE_HASH,
        "data_source": DATA_SOURCE,
        "source_labels": ["yfinance_proxy", "completed_5m_ohlcv", "completed_1h_ohlcv"],
        "evidence_tier": EVIDENCE_TIER,
        "promotion_eligible": False,
        "evidence_blockers": list(config.evidence_blockers),
        "execution_mode": "shadow_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "orders_submitted": 0,
    }


def _signal_id(config: StrategyConfig, session_date: date, decision: Mapping[str, Any]) -> str:
    plan = decision.get("plan") or {}
    actionable = str(plan.get("actionable_at") or "no_signal").replace(":", "").replace("+", "p")
    return f"{config.strategy_id}:{session_date.isoformat()}:{actionable}"


def run_entry(config: StrategyConfig, *, as_of: datetime | None = None, log_path: Path | None = None) -> int:
    as_of = (as_of or datetime.now(ET)).astimezone(ET)
    path = log_path or config.log_path
    session_date = as_of.date()
    try:
        raw = download_family_data()
        data = {
            "mnq_5m": completed_bars(raw["mnq_5m"], as_of=as_of, interval=timedelta(minutes=5)),
            "mnq_1h": completed_bars(raw["mnq_1h"], as_of=as_of, interval=timedelta(hours=1)),
            "nq_1h": completed_bars(raw["nq_1h"], as_of=as_of, interval=timedelta(hours=1)),
            "mes_1h": completed_bars(raw["mes_1h"], as_of=as_of, interval=timedelta(hours=1)),
            "es_1h": completed_bars(raw["es_1h"], as_of=as_of, interval=timedelta(hours=1)),
        }
        decision = build_entry_plan(config, data, session_date)
    except Exception as exc:
        decision = {"should_enter": False, "reason": "market_data_incomplete", "error": str(exc)[:240]}

    plan_id = _signal_id(config, session_date, decision)
    rows = _records(path)
    if any(row.get("event_type") == "entry" and row.get("plan_id") == plan_id for row in rows):
        print(json.dumps({"status": "duplicate_ignored", "plan_id": plan_id}, sort_keys=True))
        return 0
    record = _base(config, "entry", as_of) | {
        "plan_id": plan_id,
        "trade_key": plan_id,
        "session_date": session_date.isoformat(),
        "should_enter": bool(decision.get("should_enter")),
        "reason": decision.get("reason"),
        "settled": not bool(decision.get("should_enter")),
    }
    if decision.get("error"):
        record["error"] = decision["error"]
    plan = decision.get("plan")
    if plan:
        record.update({
            "plan": plan,
            "direction": plan["direction"],
            "entry_price": plan["entry_price"],
            "entry_price_observed_proxy": plan["entry_price"],
            "entry_fill_executable": None,
            "created_at": plan["actionable_at"],
            "stop_price": plan["stop_price"],
            "t1_price": plan["t1_price"],
            "t2_price": plan["t2_price"],
            "stop_distance_pts": plan["stop_distance_pts"],
            "max_risk_per_contract": plan["max_risk_per_contract"],
            "quantity": 1,
            "effective_qty": 1,
        })
    _append(record, path)
    print(json.dumps(record, sort_keys=True, separators=(",", ":")))
    return 0


def run_resolve(config: StrategyConfig, *, as_of: datetime | None = None, log_path: Path | None = None) -> int:
    as_of = (as_of or datetime.now(ET)).astimezone(ET)
    path = log_path or config.log_path
    rows = _records(path)
    exited = {str(row.get("plan_id")) for row in rows if row.get("event_type") == "exit"}
    entries = [
        row for row in rows
        if row.get("event_type") == "entry"
        and row.get("should_enter") is True
        and row.get("strategy_id") == config.strategy_id
        and str(row.get("plan_id")) not in exited
    ]
    if not entries:
        print(json.dumps({"status": "resolve_noop", "reason": "no_unsettled_entry"}, sort_keys=True))
        return 0
    try:
        raw = download_family_data()
        bars = completed_bars(raw["mnq_5m"], as_of=as_of, interval=timedelta(minutes=5))
    except Exception as exc:
        print(json.dumps({"status": "resolve_deferred", "reason": "market_data_incomplete", "error": str(exc)[:240]}, sort_keys=True))
        return 0

    resolved = 0
    for entry in entries:
        summary = resolve_plan(bars, entry["plan"], as_of=as_of)
        if summary is None:
            continue
        max_risk = float(entry.get("max_risk_per_contract") or 0.0)
        outcome_r = summary["net_dollar"] / max_risk if max_risk else None
        record = _base(config, "exit", as_of) | {
            "plan_id": entry["plan_id"],
            "trade_key": entry["plan_id"],
            "session_date": entry.get("session_date"),
            "resolved_at": utc_z(as_of),
            "entry_price": entry.get("entry_price"),
            "entry_price_observed_proxy": entry.get("entry_price_observed_proxy"),
            "exit_fill_executable": None,
            "exit_bid": None,
            "exit_price": None,
            "exit_price_observed_proxy": summary["exit_price_observed_proxy"],
            "exit_timestamp": summary["exit_timestamp"],
            "stop_price": entry.get("stop_price"),
            "t1_price": entry.get("t1_price"),
            "t2_price": entry.get("t2_price"),
            "exit_reason": summary["exit_reason"],
            "reason": summary["exit_reason"],
            "outcome": summary["outcome"],
            "outcome_r": outcome_r,
            "gross_dollar": summary["gross_dollar"],
            "pnl_before_fees": summary["gross_dollar"],
            "net_dollar": summary["net_dollar"],
            "quantity": 1,
            "detail": summary,
            "settled": True,
        }
        _append(record, path)
        resolved += 1
    print(json.dumps({"status": "resolved" if resolved else "resolve_deferred", "resolved_count": resolved}, sort_keys=True))
    return 0
