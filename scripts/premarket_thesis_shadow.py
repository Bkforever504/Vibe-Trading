#!/usr/bin/env python3
"""Build fail-honest premarket theses from radar plus verified option prints."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import governed_shadow_alert
from scripts.options_nbbo_evidence import analyze

ET = ZoneInfo("America/New_York")
VIBE_HOME = Path.home() / ".vibe-trading"
RADAR_PATH = VIBE_HOME / "reports" / "premarket-opportunity-radar.json"
NBBO_PATH = ROOT / "data" / "databento" / "options_nbbo_candidate_quotes.jsonl"
REPORT_PATH = VIBE_HOME / "reports" / "premarket-thesis-shadow.json"
STATE_PATH = VIBE_HOME / "state" / "premarket-thesis-shadow.json"
MIN_PREMIUM = 50_000.0
CORE = {"SPY", "QQQ", "IWM"}
OCC = re.compile(r"^([A-Z]{1,6})(\d{6})([CP])\d{8}$")
MAX_PRINT_AGE = timedelta(minutes=15)


def _timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(ET) if parsed.tzinfo is not None else None
    except (ValueError, TypeError):
        return None


def _positive(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def _read_json(path: Path) -> dict[str, Any]:
    try: value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError): return {}
    return value if isinstance(value, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try: lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError: return []
    rows = []
    for line in lines:
        try: value = json.loads(line)
        except json.JSONDecodeError: continue
        if isinstance(value, dict): rows.append(value)
    return rows


def _print_facts(rows: Iterable[Mapping[str, Any]], *, now_et: datetime, underlying: str) -> dict[str, Any]:
    puts = calls = put_premium = call_premium = 0.0
    unusual = []
    verified = 0
    seen: set[tuple[str, str]] = set()
    rejected: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        symbol = str(row.get("symbol") or "").replace(" ", "").upper()
        match = OCC.match(symbol)
        if not match or match.group(1) != underlying:
            continue
        # CBBO quotes are not trades. Only records explicitly identified as
        # prints/trades may support flow claims.
        stamp = _timestamp(row.get("event_at") or row.get("ts_event") or row.get("observed_at"))
        provider, trade_id = str(row.get("provider") or "").strip(), str(row.get("trade_id") or "").strip()
        reason = None
        try:
            expiry = datetime.strptime(match.group(2), "%y%m%d").date()
        except ValueError:
            expiry = None
        if str(row.get("record_type") or row.get("event_type") or "").lower() not in {"trade", "option_print"}:
            reason = "quote_is_not_trade"
        elif row.get("verified") is not True or not provider or not trade_id:
            reason = "unverified_trade_or_identity_missing"
        elif stamp is None or not timedelta(0) <= now_et - stamp <= MAX_PRINT_AGE or stamp.date() != now_et.date():
            reason = "stale_future_or_missing_event_time"
        elif expiry is None or expiry < now_et.date():
            reason = "expired_or_invalid_contract"
        elif row.get("underlying") and str(row["underlying"]).upper() != underlying:
            reason = "underlying_mismatch"
        elif (provider, trade_id) in seen:
            reason = "duplicate_trade"
        if reason:
            rejected[reason] = rejected.get(reason, 0) + 1
            continue
        premium = row.get("premium")
        if premium is None:
            price, size = row.get("price"), row.get("size")
            premium = float(price) * float(size) * 100 if _positive(price) and _positive(size) else None
        if not _positive(premium):
            rejected["invalid_premium"] = rejected.get("invalid_premium", 0) + 1
            continue
        seen.add((provider, trade_id))
        verified += 1
        if match.group(3) == "P": put_premium += float(premium); puts += 1
        else: call_premium += float(premium); calls += 1
        if premium >= MIN_PREMIUM: unusual.append({"symbol": symbol, "right": "PUT" if match.group(3) == "P" else "CALL", "premium": round(float(premium), 2), "observed_at": stamp.isoformat(), "provider": provider, "trade_id": trade_id})
    ratio = put_premium / call_premium if call_premium > 0 else None
    return {"symbol": underlying, "verified_prints": verified, "put_premium": round(put_premium, 2), "call_premium": round(call_premium, 2), "put_call_premium_ratio": round(ratio, 3) if ratio is not None else None, "unusual_prints": unusual, "rejected_records": rejected, "directional_limit": "Option right and premium do not identify buyer intent or establish a directional trade."}


def build_report(*, radar: Mapping[str, Any], nbbo_rows: Iterable[Mapping[str, Any]], now_et: datetime,
                 nbbo_status: str | None = None) -> dict[str, Any]:
    now_et = now_et.astimezone(ET)
    from scripts.signal_stack_health_report import is_expected_market_session
    in_window = is_expected_market_session(now_et.date()) and time(8, 0) <= now_et.time() <= time(9, 25)
    rows = list(nbbo_rows)
    symbol_facts = [analyze(rows, symbol, as_of=now_et.astimezone(timezone.utc)) for symbol in sorted(CORE)]
    base = {"provider": "premarket_thesis_shadow", "generated_at": now_et.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), "as_of_et": now_et.isoformat(), "execution_enabled": False, "can_submit_orders": False}
    if not in_window:
        return {**base, "status": "outside_window", "theses": [], "alert_state": "OBSERVE"}
    if nbbo_status in {"not_configured", "budget_exceeded", "timeout", "missing"}:
        symbol_facts = [{**facts, "status": "missing", "available": False, "fresh": False} for facts in symbol_facts]
    candidates = [row for row in [*(radar.get("high_priority") or []), *(radar.get("observations") or [])] if isinstance(row, Mapping)]
    expires = datetime.combine(now_et.date(), time(10, 0), ET)
    theses = []
    for facts in symbol_facts:
        symbol = facts["symbol"]
        radar_stamp = _timestamp(radar.get("generated_at"))
        gap = next((row for row in candidates if str(row.get("symbol") or "").upper() == symbol), {})
        radar_fresh = radar_stamp is not None and timedelta(0) <= now_et - radar_stamp <= MAX_PRINT_AGE
        facts["radar_context"] = dict(gap) if radar_fresh else {"status": "missing_or_stale"}
        direction = facts.get("direction") if facts.get("available") and facts.get("fresh") else "NO_BIAS"
        if direction == "NEUTRAL": direction = "NO_BIAS"
        numeric = facts.get("evidence_numeric") or {}
        summary = f"put/call $ ratio {numeric.get('put_call_dollar_premium_ratio')}, skew {numeric.get('skew_5pct')}, unusual verified directional prints {numeric.get('unusual_prints_count')}"
        thesis = {"thesis_id": hashlib.sha256(f"{now_et.date()}|{symbol}|nbbo_options_flow".encode()).hexdigest(),
                  "symbol": symbol, "direction": direction, "conviction": "medium" if direction in {"LONG", "SHORT"} else "low",
                  "setup": "nbbo_options_flow", "status": "ok" if direction in {"LONG", "SHORT"} else "missing" if not facts.get("available") else "no_bias",
                  "evidence_summary": summary, "evidence_numeric": numeric, "sources_used": ["databento_opra_nbbo"] if facts.get("available") else [],
                  "as_of": facts.get("observed_at").isoformat().replace("+00:00", "Z") if isinstance(facts.get("observed_at"), datetime) else facts.get("observed_at"),
                  "fresh": facts.get("fresh") is True, "unusual_prints": facts.get("unusual_prints") or [], "evidence": facts,
                  "generated_at": base["generated_at"], "expires_at": expires.isoformat(), "expires_at_et": "10:00",
                  "state": "OBSERVE", "execution_enabled": False, "can_submit_orders": False}
        theses.append(thesis)
    usable = sum(row["direction"] in {"LONG", "SHORT"} for row in theses)
    status = "ok" if any(facts.get("available") for facts in symbol_facts) else "missing"
    return {**base, "status": status, "feed_status": nbbo_status or status,
            "reason": None if status == "ok" else "fresh_verified_opra_nbbo_unavailable",
            "theses": theses, "evidence": symbol_facts, "directional_theses": usable, "alert_state": "OBSERVE"}


def send_observe(report: Mapping[str, Any], *, sender: Callable[[str], Mapping[str, Any]] = governed_shadow_alert.deliver, state_path: Path = STATE_PATH, now_et: datetime | None = None) -> dict[str, Any]:
    if report.get("status") != "ok" or not report.get("theses"): return {"status": "not_sent", "reason": report.get("status"), "sent": 0}
    now_et = (now_et or datetime.now(ET)).astimezone(ET)
    state = _read_json(state_path)
    sent = set(state.get("sent") or [])
    results = []
    for thesis in report["theses"]:
        tid = str(thesis.get("thesis_id") or "")
        generated, expires = _timestamp(thesis.get("generated_at")), _timestamp(thesis.get("expires_at"))
        if not tid or tid in sent:
            continue
        if generated is None or expires is None or not generated <= now_et < expires or now_et - generated > MAX_PRINT_AGE:
            continue
        if thesis.get("state") != "OBSERVE" or thesis.get("direction") not in {"LONG", "SHORT"} or thesis.get("fresh") is not True or thesis.get("execution_enabled") is not False or thesis.get("can_submit_orders") is not False:
            continue
        message = f"[PREMARKET THESIS · NBBO] OBSERVE {thesis['symbol']} {thesis['direction']} · conviction={thesis['conviction']}\n{thesis['evidence_summary']}\nExpires {thesis['expires_at']}. NBBO is critic context only; wait for deterministic confirmation. Shadow only."
        result = dict(sender(message))
        results.append(result)
        if result.get("delivered") is True:
            sent.add(tid)
            state_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = state_path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps({"sent": sorted(sent), "execution_enabled": False, "can_submit_orders": False}, indent=2) + "\n", encoding="utf-8")
            temporary.replace(state_path)
    delivered = sum(row.get("delivered") is True for row in results)
    return {"status": "sent" if delivered else "not_sent", "sent": delivered, "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--alert", action="store_true"); parser.add_argument("--report", type=Path, default=REPORT_PATH); parser.add_argument("--radar", type=Path, default=RADAR_PATH); parser.add_argument("--nbbo", type=Path, default=NBBO_PATH)
    args = parser.parse_args(); report = build_report(radar=_read_json(args.radar), nbbo_rows=_read_jsonl(args.nbbo), now_et=datetime.now(ET)); report["notification"] = send_observe(report) if args.alert else {"status": "disabled", "sent": 0}
    args.report.parent.mkdir(parents=True, exist_ok=True); args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"); print(json.dumps({"status": report["status"], "theses": len(report["theses"]), "sent": report["notification"]["sent"]}))
    return 0


if __name__ == "__main__": raise SystemExit(main())
