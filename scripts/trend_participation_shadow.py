#!/usr/bin/env python3
"""Forward-only defined-risk trend participation shadow lane."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

try:
    import requests as _requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(Path(__file__).resolve().parents[1] / "agent" / ".env")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
RUNTIME = Path.home() / ".vibe-trading"
REPORTS = RUNTIME / "reports"
LOG_PATH = ROOT / "data" / "trend_participation_shadow_log.jsonl"
REPORT_PATH = REPORTS / "trend-participation-shadow.json"
HTF_PATH = REPORTS / "higher-timeframe-market-map.json"
OPENING_PATH = REPORTS / "opening-range-breadth.json"
FORCE_PATH = REPORTS / "market-force-score.json"
CATALYST_PATH = REPORTS / "market-catalyst-calendar.json"
SYMBOLS = ("SPY", "QQQ", "NVDA")
FORWARD_START = date(2026, 8, 5)
NY = ZoneInfo("America/New_York")
OCC = re.compile(r"^([A-Z]+)(\d{6})C(\d{8})$")
FEE_PER_LEG_SIDE = 0.66
MAX_DEBIT_DOLLARS = 250.0
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
MIN_CONVICTION = 2


from scripts.market_conviction import score_conviction


def _send_discord_alert(message: str) -> None:
    if not DISCORD_WEBHOOK or not _HAS_REQUESTS:
        return
    try:
        _requests.post(DISCORD_WEBHOOK, json={"content": message}, timeout=5)
    except Exception:
        pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _read_log(path: Path = LOG_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _append(row: dict[str, Any], path: Path = LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")


def _by_symbol(report: dict[str, Any], key: str) -> dict[str, dict[str, Any]]:
    rows = report.get(key) if isinstance(report.get(key), list) else []
    return {
        str(row.get("symbol") or "").upper(): row
        for row in rows if isinstance(row, dict) and row.get("symbol")
    }


def qualify_symbol(
    symbol: str,
    htf: dict[str, Any],
    opening: dict[str, Any],
    force: dict[str, Any],
    catalyst: dict[str, Any],
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if htf.get("primary_bias") != "bullish" or htf.get("intraday_alignment") != "aligned":
        reasons.append("higher_timeframes_not_bullish_aligned")
    if opening.get("state") != "above_opening_range":
        reasons.append("not_above_opening_range")
    if force.get("classification") not in {"bullish", "bullish_lean"}:
        reasons.append("market_force_not_bullish")
    if bool((force.get("risk_veto") or {}).get("active")):
        reasons.append("market_force_risk_veto")
    today = catalyst.get("today") if isinstance(catalyst.get("today"), dict) else {}
    if today.get("max_impact") == "high":
        reasons.append("high_impact_event_day")
    if today.get("caution_windows"):
        reasons.append("active_event_caution_window")
    return not reasons, reasons


def _contract_fields(row: dict[str, Any]) -> tuple[str, date] | None:
    symbol = str(row.get("option_symbol") or "").upper()
    match = OCC.fullmatch(symbol)
    if not match:
        return None
    return match.group(1), datetime.strptime(match.group(2), "%y%m%d").date()


def select_call_debit_spread(rows: list[dict[str, Any]], today: date) -> dict[str, Any] | None:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        parsed = _contract_fields(row)
        try:
            delta = abs(float(row.get("delta")))
            bid = float(row.get("bid"))
            ask = float(row.get("ask"))
            strike = float(row.get("strike"))
            spread_pct = float(row.get("spread_pct"))
        except (TypeError, ValueError):
            continue
        if not parsed or bid <= 0 or ask < bid or spread_pct > 15:
            continue
        _, expiry = parsed
        dte = (expiry - today).days
        if 7 <= dte <= 21:
            normalized.append({**row, "delta_abs": delta, "expiry": expiry.isoformat(), "dte": dte, "strike": strike})
    longs = [row for row in normalized if 0.50 <= row["delta_abs"] <= 0.70]
    shorts = [row for row in normalized if 0.25 <= row["delta_abs"] <= 0.40]
    candidates: list[dict[str, Any]] = []
    for long in longs:
        for short in shorts:
            if short["expiry"] != long["expiry"] or short["strike"] <= long["strike"]:
                continue
            width = short["strike"] - long["strike"]
            debit = float(long["ask"]) - float(short["bid"])
            if debit <= 0 or debit >= width or debit > 0.55 * width or debit * 100 > MAX_DEBIT_DOLLARS:
                continue
            max_profit = width - debit
            score = (
                abs(long["delta_abs"] - 0.60) + abs(short["delta_abs"] - 0.33)
                + (float(long["spread_pct"]) + float(short["spread_pct"])) / 100
                - min(max_profit / debit, 3.0) / 10
            )
            candidates.append({
                "long": long, "short": short, "width": round(width, 4),
                "entry_debit": round(debit, 4), "max_loss_dollars": round(debit * 100, 2),
                "max_profit_dollars": round(max_profit * 100, 2),
                "reward_risk": round(max_profit / debit, 4), "selection_score": round(score, 6),
            })
    return min(candidates, key=lambda row: row["selection_score"]) if candidates else None


def _open_symbols(rows: list[dict[str, Any]]) -> set[str]:
    state: dict[str, str] = {}
    for row in rows:
        candidate_id = str(row.get("candidate_id") or "")
        if candidate_id and row.get("type") in {"candidate", "outcome"}:
            state[candidate_id] = str(row.get("type"))
    return {
        str(row.get("symbol")) for row in rows
        if row.get("type") == "candidate" and state.get(str(row.get("candidate_id"))) == "candidate"
    }


def _existing_session_symbols(rows: list[dict[str, Any]], session: str) -> set[str]:
    return {
        str(row.get("symbol")) for row in rows
        if row.get("type") == "candidate" and row.get("session") == session
    }


def executable_close_value(candidate: dict[str, Any], quotes: dict[str, dict[str, Any]]) -> float | None:
    spread = candidate.get("spread") if isinstance(candidate.get("spread"), dict) else {}
    long_symbol = str((spread.get("long") or {}).get("option_symbol") or "")
    short_symbol = str((spread.get("short") or {}).get("option_symbol") or "")
    try:
        long_bid = float(quotes[long_symbol]["bid"])
        short_ask = float(quotes[short_symbol]["ask"])
    except (KeyError, TypeError, ValueError):
        return None
    value = long_bid - short_ask
    return round(value, 4) if value >= 0 else None


def evaluate_mark(candidate: dict[str, Any], close_value: float, observed_on: date) -> dict[str, Any]:
    spread = candidate["spread"]
    entry = float(spread["entry_debit"])
    fee = float(candidate.get("fee_per_leg_side", FEE_PER_LEG_SIDE))
    gross = (close_value - entry) * 100
    base_fees = fee * 4
    reason = None
    if close_value >= float(candidate["profit_target_close_value"]):
        reason = "profit_target"
    elif close_value <= float(candidate["stop_close_value"]):
        reason = "stop_loss"
    else:
        opened = date.fromisoformat(str(candidate["session"]))
        expiry = date.fromisoformat(str(spread["long"]["expiry"]))
        if (observed_on - opened).days >= int(candidate.get("max_holding_calendar_days", 7)):
            reason = "max_holding_time"
        elif (expiry - observed_on).days <= 2:
            reason = "two_dte"
    return {
        "close_value": round(close_value, 4), "gross_pnl": round(gross, 2),
        "pnl_base_fees": round(gross - base_fees, 2),
        "pnl_double_fees": round(gross - 2 * base_fees, 2),
        "reason": reason, "resolved": reason is not None,
    }


def build_entry_report(
    trading_day: date | None = None,
    *,
    contract_fetcher: Callable[..., list[dict[str, Any]]] | None = None,
    log_path: Path = LOG_PATH,
) -> dict[str, Any]:
    trading_day = trading_day or datetime.now(NY).date()
    base: dict[str, Any] = {
        "provider": "trend_participation_shadow", "mode": "forward_only_shadow",
        "date": trading_day.isoformat(), "execution_enabled": False, "can_submit_orders": False,
        "candidates": [], "rejections": [],
    }
    if trading_day < FORWARD_START:
        return {**base, "status": "consumed_design_day_not_evidence"}
    if contract_fetcher is None:
        from scripts.liquid_options_edge_shadow import fetch_contract_candidates
        contract_fetcher = fetch_contract_candidates
    htf_report = _read_json(HTF_PATH)
    opening_report = _read_json(OPENING_PATH)
    force = _read_json(FORCE_PATH)
    catalyst = _read_json(CATALYST_PATH)
    htf = _by_symbol(htf_report, "items")
    opening = _by_symbol(opening_report, "scans")
    existing = _read_log(log_path)
    unavailable = _open_symbols(existing) | _existing_session_symbols(existing, trading_day.isoformat())
    for symbol in SYMBOLS:
        if symbol in unavailable:
            base["rejections"].append({"symbol": symbol, "reasons": ["existing_open_or_session_candidate"]})
            continue
        qualified, reasons = qualify_symbol(symbol, htf.get(symbol, {}), opening.get(symbol, {}), force, catalyst)
        if not qualified:
            base["rejections"].append({"symbol": symbol, "reasons": reasons})
            continue
        try:
            contracts = contract_fetcher(symbol, "long", min_dte=7, max_dte=21)
            spread = select_call_debit_spread(contracts, trading_day)
        except Exception as exc:
            spread = None
            reasons = [f"option_chain_error:{type(exc).__name__}"]
        if spread is None:
            base["rejections"].append({"symbol": symbol, "reasons": reasons or ["no_qualified_debit_spread"]})
            continue
        candidate_id = f"trend-debit:{symbol}:{trading_day.isoformat()}"
        row = {
            "type": "candidate", "candidate_id": candidate_id, "session": trading_day.isoformat(),
            "captured_at": datetime.now(timezone.utc).isoformat(), "symbol": symbol,
            "strategy": "call_debit_spread", "spread": spread,
            "profit_target_close_value": round(spread["entry_debit"] + 0.5 * (spread["width"] - spread["entry_debit"]), 4),
            "stop_close_value": round(0.5 * spread["entry_debit"], 4),
            "max_holding_calendar_days": 7, "fee_per_leg_side": FEE_PER_LEG_SIDE,
            "quote_scope": str(spread["long"].get("quote_scope") or "unknown"),
            "execution_enabled": False, "can_submit_orders": False,
            "conviction": score_conviction(symbol, trading_day),
        }
        _append(row, log_path)
        base["candidates"].append(row)
        conviction = row["conviction"]
        sig_ok = ", ".join(k for k, v in conviction["signals"].items() if v.startswith("ok:"))
        _send_discord_alert(
            f"@everyone **SHADOW ALERT [{symbol}] Call Debit Spread candidate**\n"
            f"Entry debit: ${spread['entry_debit'] * 100:.2f} | Max loss: ${spread['max_loss_dollars']:.0f} | "
            f"R/R: {spread['reward_risk']:.2f}\n"
            f"Conviction: {conviction['conviction_score']}/{conviction['conviction_max']} — {sig_ok}\n"
            f"Market force: {force.get('classification', 'unknown')}\n"
            f"SHADOW ONLY — no order submitted. Evidence building."
        )
    base["status"] = "candidates_recorded" if base["candidates"] else "no_qualified_candidates"
    return base


def build_monitor_report(
    observed_on: date | None = None,
    *,
    contract_fetcher: Callable[..., list[dict[str, Any]]] | None = None,
    log_path: Path = LOG_PATH,
) -> dict[str, Any]:
    observed_on = observed_on or datetime.now(NY).date()
    report: dict[str, Any] = {
        "provider": "trend_participation_shadow", "mode": "forward_only_shadow_monitor",
        "date": observed_on.isoformat(), "execution_enabled": False, "can_submit_orders": False,
        "marks": [], "outcomes": [], "blockers": [],
    }
    if contract_fetcher is None:
        from scripts.liquid_options_edge_shadow import fetch_contract_candidates
        contract_fetcher = fetch_contract_candidates
    rows = _read_log(log_path)
    state: dict[str, str] = {}
    candidates: dict[str, dict[str, Any]] = {}
    for row in rows:
        candidate_id = str(row.get("candidate_id") or "")
        if not candidate_id:
            continue
        if row.get("type") == "candidate":
            candidates[candidate_id] = row
            state[candidate_id] = "open"
        elif row.get("type") == "outcome":
            state[candidate_id] = "resolved"
    for candidate_id, candidate in candidates.items():
        if state.get(candidate_id) != "open":
            continue
        symbol = str(candidate["symbol"])
        try:
            chain = contract_fetcher(symbol, "long", min_dte=0, max_dte=30)
            quotes = {str(row.get("option_symbol") or ""): row for row in chain}
            close_value = executable_close_value(candidate, quotes)
        except Exception as exc:
            close_value = None
            report["blockers"].append(f"{candidate_id}:quote_error:{type(exc).__name__}")
        if close_value is None:
            report["blockers"].append(f"{candidate_id}:incomplete_close_quote")
            continue
        evaluation = evaluate_mark(candidate, close_value, observed_on)
        mark = {
            "type": "mark", "candidate_id": candidate_id, "symbol": symbol,
            "observed_at": datetime.now(timezone.utc).isoformat(), **evaluation,
            "execution_enabled": False, "can_submit_orders": False,
        }
        _append(mark, log_path)
        report["marks"].append(mark)
        if evaluation["resolved"]:
            outcome = {**mark, "type": "outcome"}
            _append(outcome, log_path)
            report["outcomes"].append(outcome)
            pnl = evaluation["pnl_double_fees"]
            emoji = "✅" if pnl >= 0 else "❌"
            _send_discord_alert(
                f"{emoji} **SHADOW CLOSE [{symbol}] Call Debit Spread**\n"
                f"Reason: {evaluation['reason']} | Close value: {evaluation['close_value']}\n"
                f"P&L (2× fees): ${pnl:.2f}\n"
                f"SHADOW ONLY — no order submitted."
            )
    report["status"] = "ok"
    return report


def build_morning_regime_alert(trading_day: date | None = None) -> dict[str, Any]:
    trading_day = trading_day or datetime.now(NY).date()
    htf_report = _read_json(HTF_PATH)
    opening_report = _read_json(OPENING_PATH)
    force = _read_json(FORCE_PATH)
    htf = _by_symbol(htf_report, "items")
    opening = _by_symbol(opening_report, "scans")
    spy_htf = htf.get("SPY", {})
    spy_opening = opening.get("SPY", {})
    force_class = str(force.get("classification") or "")
    htf_bullish = spy_htf.get("primary_bias") == "bullish" and spy_htf.get("intraday_alignment") == "aligned"
    above_range = spy_opening.get("state") == "above_opening_range"
    bullish_force = force_class in {"bullish", "bullish_lean"}
    result: dict[str, Any] = {
        "provider": "trend_participation_shadow", "mode": "morning_regime_alert",
        "date": trading_day.isoformat(), "htf_bullish_aligned": htf_bullish,
        "spy_above_opening_range": above_range, "force_classification": force_class,
        "alert_sent": False,
    }
    if htf_bullish and above_range and bullish_force:
        _send_discord_alert(
            f"🌅 **MORNING REGIME ALERT [{trading_day}]**\n"
            f"Market force: {force_class} | SPY above opening range | HTF bullish+aligned\n"
            f"Trend participation scanner watching for call debit spread setups."
        )
        result["alert_sent"] = True
    result["status"] = "alert_sent" if result["alert_sent"] else "regime_not_aligned"
    return result


def _write_report(report: dict[str, Any], path: Path = REPORT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temp, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat)
    parser.add_argument("--mode", choices=("entry", "monitor", "morning"), default="entry")
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    parser.add_argument("--log", type=Path, default=LOG_PATH)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    if args.mode == "entry":
        report = build_entry_report(args.date, log_path=args.log)
    elif args.mode == "monitor":
        report = build_monitor_report(args.date, log_path=args.log)
    else:
        report = build_morning_regime_alert(args.date)
    _write_report(report, args.report)
    print(json.dumps(report, indent=2, sort_keys=True) if args.print_report else report["status"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
