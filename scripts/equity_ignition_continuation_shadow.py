#!/usr/bin/env python3
"""EOD ignition-contraction-continuation equity challenger (shadow only)."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_PATH = VIBE_HOME / "reports" / "equity-ignition-continuation-shadow.json"
LOG_PATH = ROOT / "data" / "equity_ignition_continuation_shadow_log.jsonl"
UNIVERSE_PATH = ROOT / "data" / "universes" / "equity_scout_v1_membership_2026-08-23.json"
SPEC_PATH = "research/preregistrations/equity_ignition_contraction_continuation_v1.md"
STRATEGY_ID = "equity-ignition-contraction-continuation-v1"
FAMILY_ID = "equity-swing-continuation"
SPEC_HASH = "sha256:c3ba4bac6145e2c4a05935e17aa92673acf5f827ca36b3a2ffb5453e8a65a5fd"
EXPECTED_UNIVERSE_HASH = "sha256:e69d15099e63f70b4e41f4c8d9457074581063b556cb678671abf3102a8d46a0"
UNIVERSE_ID = "equity-scout-hot20-plus-sp100-liquid"
UNIVERSE_VERSION = "equity-scout-hot20-plus-sp100-liquid-v1"
DATA_SOURCE = "yfinance_adjusted_daily_proxy"
EVIDENCE_TIER = "completed_daily_ohlcv_shadow_proxy"
EVIDENCE_BLOCKERS = ["executable_nbbo_quotes_required", "resolved_forward_outcomes_required", "kenny_signoff_required"]


def _float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _normalized(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    result = frame.copy()
    result.columns = [str(value).title() for value in result.columns]
    required = ["Open", "High", "Low", "Close", "Volume"]
    if any(column not in result for column in required):
        return pd.DataFrame()
    return result[required].apply(pd.to_numeric, errors="coerce").dropna().sort_index()


def _return(frame: pd.DataFrame, periods: int = 20) -> float | None:
    if len(frame) <= periods:
        return None
    start = _float(frame["Close"].iloc[-periods - 1])
    end = _float(frame["Close"].iloc[-1])
    return end / start - 1.0 if start and end is not None else None


def _atr(frame: pd.DataFrame, periods: int = 14) -> float:
    previous = frame["Close"].shift(1)
    true_range = pd.concat([
        frame["High"] - frame["Low"],
        (frame["High"] - previous).abs(),
        (frame["Low"] - previous).abs(),
    ], axis=1).max(axis=1)
    return float(true_range.tail(periods).mean())


def evaluate_symbol(
    symbol: str,
    daily: pd.DataFrame,
    *,
    benchmark: pd.DataFrame | None,
    sector: pd.DataFrame | None,
) -> dict[str, Any]:
    frame = _normalized(daily)
    benchmark_frame = _normalized(benchmark)
    sector_frame = _normalized(sector)
    blockers: list[str] = []
    if len(frame) < 60:
        blockers.append("insufficient_completed_daily_bars")
    if benchmark_frame.empty:
        blockers.append("benchmark_context_missing")
    if sector_frame.empty:
        blockers.append("sector_context_missing")
    if blockers and len(frame) < 60:
        return {
            "symbol": symbol.upper(), "setup_family": "ignition_contraction_continuation",
            "state": "BLOCKED", "blockers": blockers, "promotion_eligible": False,
            "execution_enabled": False, "can_submit_orders": False,
        }

    close = frame["Close"]
    volume = frame["Volume"]
    ema8 = close.ewm(span=8, adjust=False).mean()
    ema21 = close.ewm(span=21, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    ema_stack = bool(ema8.iloc[-1] > ema21.iloc[-1] > ema50.iloc[-1])

    ignition_index: int | None = None
    ignition_ratio = 0.0
    for index in range(max(20, len(frame) - 11), len(frame) - 2):
        prior_average = float(volume.iloc[index - 20:index].mean())
        day_return = float(close.iloc[index] / close.iloc[index - 1] - 1.0)
        ratio = float(volume.iloc[index] / prior_average) if prior_average > 0 else 0.0
        if day_return >= 0.02 and ratio >= 1.8:
            ignition_index, ignition_ratio = index, ratio
    if ignition_index is None:
        blockers.append("qualifying_ignition_day_missing")
        ignition_index = max(0, len(frame) - 10)

    # The latest row is the breakout candidate, never part of the base.
    contraction_rows = frame.iloc[ignition_index + 1:-1]
    ignition_volume = float(volume.iloc[ignition_index])
    contracted = bool(not contraction_rows.empty and float(contraction_rows["Volume"].mean()) <= ignition_volume * 0.75)
    base_range_pct = float((contraction_rows["High"].max() - contraction_rows["Low"].min()) / close.iloc[ignition_index]) if not contraction_rows.empty else 1.0
    tight = bool(2 <= len(contraction_rows) <= 10 and base_range_pct <= 0.08)
    if not contracted:
        blockers.append("pullback_volume_not_contracted")
    if not tight:
        blockers.append("base_not_tight_or_duration_outside_2_10_days")

    prior_high = float(contraction_rows["High"].max()) if not contraction_rows.empty else float(frame["High"].iloc[-2])
    average_volume = float(volume.iloc[-21:-1].mean())
    breakout = bool(float(close.iloc[-1]) > prior_high)
    volume_expanded = bool(average_volume > 0 and float(volume.iloc[-1]) / average_volume >= 1.3)
    if not breakout:
        blockers.append("completed_daily_breakout_not_confirmed")
    if not volume_expanded:
        blockers.append("breakout_volume_not_expanded")
    if not ema_stack:
        blockers.append("ema_stack_not_8_above_21_above_50")

    stock_return = _return(frame)
    benchmark_return = _return(benchmark_frame) if not benchmark_frame.empty else None
    sector_return = _return(sector_frame) if not sector_frame.empty else None
    rs_market = stock_return - benchmark_return if stock_return is not None and benchmark_return is not None else None
    sector_leading = bool(sector_return is not None and benchmark_return is not None and sector_return > benchmark_return)
    if rs_market is None or rs_market < 0.03:
        blockers.append("relative_strength_vs_spy_below_3pct_or_missing")
    if not sector_leading:
        blockers.append("sector_not_leading_spy_or_missing")

    atr = max(_atr(frame), float(close.iloc[-1]) * 0.005)
    entry = float(frame["High"].iloc[-1]) + 0.05 * atr
    base_low = float(contraction_rows["Low"].min()) if not contraction_rows.empty else float(frame["Low"].iloc[-1])
    stop = min(base_low, float(ema21.iloc[-1])) - 0.10 * atr
    risk = max(0.0, entry - stop)
    target = entry + 2.0 * risk if risk > 0 else None
    core_blockers = [item for item in blockers if item not in {"benchmark_context_missing", "sector_context_missing"}]
    state = "SHADOW_READY" if not blockers else "WATCH" if len(core_blockers) <= 2 and ignition_ratio >= 1.8 else "BLOCKED"
    score = max(0.0, 100.0 - 10.0 * len(set(blockers)))
    signal_date = str(getattr(frame.index[-1], "date", lambda: frame.index[-1])())[:10]
    plan_id = f"{STRATEGY_ID}:{symbol.upper()}:{signal_date}"
    return {
        "symbol": symbol.upper(),
        "plan_id": plan_id,
        "strategy_id": STRATEGY_ID,
        "family_id": FAMILY_ID,
        "spec_hash": SPEC_HASH,
        "spec_path": SPEC_PATH,
        "universe_id": UNIVERSE_ID,
        "universe_version": UNIVERSE_VERSION,
        "universe_hash": EXPECTED_UNIVERSE_HASH,
        "signal_date": signal_date,
        "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "data_source": DATA_SOURCE,
        "setup_family": "ignition_contraction_continuation",
        "state": state,
        "grade": "A" if score >= 85 else "B" if score >= 70 else "C" if score >= 55 else "D",
        "score": score,
        "ema_stack": "8_above_21_above_50" if ema_stack else "not_aligned",
        "ignition": {"bar_index": ignition_index, "volume_ratio": round(ignition_ratio, 3), "minimum_ratio": 1.8},
        "contraction": {"bars": len(contraction_rows), "range_pct": round(base_range_pct * 100, 3), "volume_contracted": contracted},
        "confirmation": {"completed_daily_breakout": breakout, "volume_expanded": volume_expanded, "minimum_volume_ratio": 1.3},
        "relative_strength": {"stock_20d": stock_return, "vs_spy_20d": rs_market, "sector_20d": sector_return, "sector_leading": sector_leading},
        "entry": round(entry, 4),
        "entry_price": round(entry, 4),
        "stop": round(stop, 4),
        "target_2r": round(target, 4) if target is not None else None,
        "atr": round(atr, 4),
        "max_risk_per_contract": round(risk, 4),
        "entry_rule": "next_session_only_after_completed_daily_breakout; revalidate quote and gap before manual review",
        "blockers": list(dict.fromkeys(blockers)),
        "evidence_tier": EVIDENCE_TIER,
        "evidence_blockers": EVIDENCE_BLOCKERS,
        "source_labels": ["completed_adjusted_daily_ohlcv", "sector_rotation_completed_daily_proxy", "frozen_universe_membership"],
        "promotion_eligible": False,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _extract(bundle: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if isinstance(bundle.columns, pd.MultiIndex):
        if symbol in bundle.columns.get_level_values(0):
            return bundle[symbol].dropna(how="all")
        if symbol in bundle.columns.get_level_values(-1):
            return bundle.xs(symbol, axis=1, level=-1).dropna(how="all")
    return bundle if not isinstance(bundle.columns, pd.MultiIndex) else pd.DataFrame()


def _validated_universe(path: Path = UNIVERSE_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    symbols = sorted(set(str(value).upper() for value in payload.get("symbols") or []))
    canonical = "\n".join(symbols) + "\n"
    computed = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    declared = str(payload.get("sha256_membership_hash") or "")
    if declared != EXPECTED_UNIVERSE_HASH or computed != EXPECTED_UNIVERSE_HASH:
        raise ValueError(f"universe_membership_hash_mismatch declared={declared} computed={computed}")
    if payload.get("universe_id") != UNIVERSE_ID or payload.get("universe_version") != UNIVERSE_VERSION:
        raise ValueError("universe_identity_mismatch")
    if int(payload.get("symbol_count") or 0) != len(symbols):
        raise ValueError("universe_symbol_count_mismatch")
    return {**payload, "symbols": symbols, "computed_membership_hash": computed}


def _universe() -> list[str]:
    return list(_validated_universe()["symbols"])


def resolve_next_session(signal: Mapping[str, Any], bar: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve one next-session daily proxy conservatively and adverse-first."""
    entry_trigger = _float(signal.get("entry"))
    stop = _float(signal.get("stop"))
    target = _float(signal.get("target_2r"))
    atr = _float(signal.get("atr"))
    open_price = _float(bar.get("Open"))
    high = _float(bar.get("High"))
    low = _float(bar.get("Low"))
    close = _float(bar.get("Close"))
    session_date = str(bar.get("date") or "")[:10]
    if None in {entry_trigger, stop, target, atr, open_price, high, low, close}:
        raise ValueError("next_session_bar_or_signal_geometry_incomplete")
    assert entry_trigger is not None and stop is not None and target is not None and atr is not None
    assert open_price is not None and high is not None and low is not None and close is not None
    risk = entry_trigger - stop
    entry_fill: float | None = None
    exit_price: float | None = None
    reason: str
    outcome = "no_fill"
    if risk <= 0:
        reason = "invalid_signal_geometry"
    elif open_price <= stop:
        reason = "open_below_invalidation"
    elif open_price >= target:
        reason = "opening_gap_consumed_target_no_chase"
    elif open_price > entry_trigger + 0.25 * atr:
        reason = "opening_gap_skipped_trigger_by_more_than_0_25_atr"
    elif high < entry_trigger:
        reason = "trigger_not_reached_next_session"
    else:
        entry_fill = max(open_price, entry_trigger)
        if low <= stop:
            exit_price = stop
            reason = "stop_adverse_first"
        elif high >= target:
            exit_price = target
            reason = "target_2r"
        else:
            exit_price = close
            reason = "final_regular_session_bar"
        gross = exit_price - entry_fill
        net = gross - 0.03  # $0.005/share/side commission + $0.01/share/side slippage.
        outcome_r = net / max(entry_fill - stop, 1e-9)
        outcome = "win" if net > 0 else "loss" if net < 0 else "scratch"
    if entry_fill is None or exit_price is None:
        gross = 0.0
        net = 0.0
        outcome_r = 0.0
    resolved_at = f"{session_date}T20:00:00Z" if session_date else datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "event_type": "outcome",
        "type": "outcome",
        "plan_id": signal.get("plan_id"),
        "candidate_id": STRATEGY_ID,
        "strategy_id": STRATEGY_ID,
        "family_id": FAMILY_ID,
        "spec_hash": signal.get("spec_hash") or SPEC_HASH,
        "symbol": signal.get("symbol"),
        "session_date": session_date or None,
        "entry_price": entry_fill,
        "exit_price": exit_price,
        "pnl_before_fees": round(gross, 6),
        "net_dollar": round(net, 6),
        "outcome_r": round(outcome_r, 6),
        "outcome": outcome,
        "terminal_reason": reason,
        "reason": reason,
        "resolved_at": resolved_at,
        "quantity": 1,
        "data_source": DATA_SOURCE,
        "evidence_tier": EVIDENCE_TIER,
        "evidence_blockers": EVIDENCE_BLOCKERS,
        "promotion_eligible": False,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def revalidate_candidate(
    candidate: Mapping[str, Any],
    *,
    open_price: float,
    current_price: float,
    completed_close: float,
) -> dict[str, Any]:
    """Apply the frozen next-open gap and completed-close checks."""
    row = dict(candidate)
    entry = _float(row.get("entry"))
    stop = _float(row.get("stop"))
    target = _float(row.get("target_2r"))
    atr = _float(row.get("atr"))
    blockers = [str(value) for value in row.get("blockers") or [] if str(value) != "next_open_revalidation_required"]
    state = "WAIT_FOR_CONFIRMATION"
    reason = "completed_5m_close_below_trigger"
    completed_confirmation = False
    if None in {entry, stop, target, atr}:
        state, reason = "BLOCKED", "signal_geometry_incomplete"
    else:
        assert entry is not None and stop is not None and target is not None and atr is not None
        if open_price <= stop:
            state, reason = "INVALID", "open_below_invalidation"
        elif open_price >= target:
            state, reason = "NO_CHASE", "opening_gap_consumed_target_no_chase"
        elif open_price > entry + 0.25 * atr:
            state, reason = "NO_CHASE", "opening_gap_skipped_trigger_by_more_than_0_25_atr"
        elif completed_close >= entry and current_price >= entry:
            state, reason = "READY_TO_REVIEW", "completed_5m_close_above_trigger_and_hold"
            completed_confirmation = True
        if state in {"BLOCKED", "INVALID", "NO_CHASE"}:
            blockers.append(reason)
    row.update({
        "state": state,
        "blockers": list(dict.fromkeys(blockers)),
        "open_revalidation": {
            "status": reason,
            "open": round(float(open_price), 4),
            "current_price": round(float(current_price), 4),
            "completed_5m_close": round(float(completed_close), 4),
            "completed_confirmation": completed_confirmation,
            "source_label": "yfinance_completed_5m_proxy",
        },
        "execution_enabled": False,
        "can_submit_orders": False,
    })
    return row


def _read_log(path: Path = LOG_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    output: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            output.append(row)
    return output


def resolve_pending(bundle: pd.DataFrame, *, rows: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    ledger = rows if rows is not None else _read_log()
    resolved = {str(row.get("plan_id")) for row in ledger if row.get("event_type") == "outcome" and row.get("plan_id")}
    pending: dict[str, dict[str, Any]] = {}
    for report in ledger:
        for candidate in report.get("observations") or report.get("candidates") or []:
            if isinstance(candidate, dict) and candidate.get("state") == "SHADOW_READY" and candidate.get("plan_id") not in resolved:
                pending[str(candidate["plan_id"])] = candidate
    outcomes: list[dict[str, Any]] = []
    for signal in pending.values():
        frame = _normalized(_extract(bundle, str(signal.get("symbol") or "")))
        if frame.empty:
            continue
        next_rows = frame[[str(index)[:10] > str(signal.get("signal_date") or "")[:10] for index in frame.index]]
        if next_rows.empty:
            continue
        index = next_rows.index[0]
        bar = next_rows.iloc[0].to_dict()
        bar["date"] = str(index)[:10]
        outcomes.append(resolve_next_session(signal, bar))
    return outcomes


def revalidate_report(report_path: Path = REPORT_PATH) -> dict[str, Any]:
    import yfinance as yf

    try:
        prior = json.loads(report_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {
            "schema_version": 1,
            "provider": "equity_ignition_continuation_shadow",
            "mode": "next_open_revalidation",
            "status": "blocked_missing_prior_eod_report",
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "candidates": [],
            "observations": [],
            "execution_enabled": False,
            "can_submit_orders": False,
        }
    candidates = [dict(row) for row in prior.get("candidates") or [] if isinstance(row, dict)]
    symbols = [str(row.get("symbol") or "") for row in candidates if row.get("symbol")]
    bundle = yf.download(symbols, period="5d", interval="5m", auto_adjust=True, progress=False, group_by="ticker", threads=True, prepost=False) if symbols else pd.DataFrame()
    revalidated: list[dict[str, Any]] = []
    for candidate in candidates:
        frame = _normalized(_extract(bundle, str(candidate.get("symbol") or "")))
        if len(frame) < 2:
            blocked = dict(candidate)
            blocked["state"] = "BLOCKED"
            blocked["blockers"] = list(dict.fromkeys([*(str(value) for value in blocked.get("blockers") or []), "completed_5m_open_revalidation_missing"]))
            revalidated.append(blocked)
            continue
        latest_date = frame.index[-1].date()
        session = frame[[index.date() == latest_date for index in frame.index]]
        if len(session) < 2:
            blocked = dict(candidate)
            blocked["state"] = "BLOCKED"
            blocked["blockers"] = list(dict.fromkeys([*(str(value) for value in blocked.get("blockers") or []), "completed_5m_open_revalidation_missing"]))
            revalidated.append(blocked)
            continue
        revalidated.append(revalidate_candidate(
            candidate,
            open_price=float(session["Open"].iloc[0]),
            current_price=float(session["Close"].iloc[-1]),
            completed_close=float(session["Close"].iloc[-2]),
        ))
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        **prior,
        "mode": "next_open_revalidation",
        "status": "revalidated" if revalidated else "no_candidates_to_revalidate",
        "generated_at": now,
        "summary": {**dict(prior.get("summary") or {}), "open_revalidated": len(revalidated)},
        "observations": revalidated,
        "candidates": revalidated,
        "terminal_events": [],
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def build_report(symbols: list[str] | None = None) -> dict[str, Any]:
    import yfinance as yf
    try:
        from scripts.equity_orb_scout_v2_shadow import SECTOR_ETFS, _SYMBOL_TO_SECTOR
    except ModuleNotFoundError:  # Direct ``python scripts\\...`` scheduler entrypoint.
        from equity_orb_scout_v2_shadow import SECTOR_ETFS, _SYMBOL_TO_SECTOR

    symbols = symbols or _universe()
    context_symbols = sorted(set([*symbols, "SPY", *SECTOR_ETFS.values()]))
    bundle = yf.download(context_symbols, period="9mo", interval="1d", auto_adjust=True, progress=False, group_by="ticker", threads=True)
    spy = _extract(bundle, "SPY")
    rows = []
    for symbol in symbols:
        sector_name = _SYMBOL_TO_SECTOR.get(symbol)
        sector_symbol = SECTOR_ETFS.get(sector_name or "")
        rows.append(evaluate_symbol(symbol, _extract(bundle, symbol), benchmark=spy, sector=_extract(bundle, sector_symbol) if sector_symbol else None))
    rows.sort(key=lambda row: (-float(row.get("score") or 0), row["symbol"]))
    display_candidates = [row for row in rows if row.get("state") in {"SHADOW_READY", "WATCH"}][:20]
    terminal_events = resolve_pending(bundle)
    return {
        "schema_version": 1,
        "provider": "equity_ignition_continuation_shadow",
        "mode": "read_only_shadow_research",
        "strategy_id": STRATEGY_ID,
        "family_id": FAMILY_ID,
        "spec_hash": SPEC_HASH,
        "spec_path": SPEC_PATH,
        "universe_id": UNIVERSE_ID,
        "universe_version": UNIVERSE_VERSION,
        "universe_hash": EXPECTED_UNIVERSE_HASH,
        "data_source": DATA_SOURCE,
        "evidence_tier": EVIDENCE_TIER,
        "evidence_blockers": EVIDENCE_BLOCKERS,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "promotion_eligible": False,
        "summary": {
            "symbols_scanned": len(rows),
            "shadow_ready": sum(row.get("state") == "SHADOW_READY" for row in rows),
            "watch": sum(row.get("state") == "WATCH" for row in rows),
            "outcomes_resolved_this_run": len(terminal_events),
        },
        "observations": rows,
        "candidates": display_candidates,
        "terminal_events": terminal_events,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def persist(report: Mapping[str, Any], report_path: Path = REPORT_PATH, log_path: Path = LOG_PATH) -> None:
    clean_report = dict(report)
    terminal_events = [dict(row) for row in clean_report.pop("terminal_events", []) if isinstance(row, Mapping)]
    report_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(clean_report, indent=2, default=str) + "\n", encoding="utf-8")
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(clean_report, separators=(",", ":"), default=str) + "\n")
        for event in terminal_events:
            handle.write(json.dumps(event, separators=(",", ":"), default=str) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("scan", "revalidate"), default="scan")
    parser.add_argument("--symbols", nargs="*")
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = revalidate_report() if args.mode == "revalidate" else build_report(args.symbols)
    persist(report)
    if args.print_report:
        print(json.dumps(report, indent=2))
    else:
        print(f"Wrote {len(report.get('candidates') or [])} shadow candidates to {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
