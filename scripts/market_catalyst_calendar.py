#!/usr/bin/env python3
"""Read-only macro event catalyst calendar.

Encodes upcoming high-impact macro events and produces a daily risk window,
veto list, and allowed playbooks for Shadow Consensus. No broker calls, no
orders, no settings changes.

Sources:
  BLS CPI schedule: https://www.bls.gov/schedule/news_release/cpi.htm
  Federal Reserve calendar: https://www.federalreserve.gov/newsevents/calendar.htm
  FOMC calendars: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
  BEA schedule: https://www.bea.gov/news/schedule
  Treasury auctions: https://home.treasury.gov/system/files/221/Tentative-Auction-Schedule.pdf
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_DIR = VIBE_HOME / "reports"
REPORT_PATH = REPORT_DIR / "market-catalyst-calendar.json"
LOG_PATH = ROOT / "data" / "market_catalyst_calendar_log.jsonl"
DYNAMIC_RISK_PATH = REPORT_DIR / "geopolitical-risk-context.json"

# ---------------------------------------------------------------------------
# Hardcoded 2026 macro calendar (July–December).
# Impact: "high" = full veto window, "medium" = size-down, "low" = note only.
# veto_type: "pre_event" = before release, "intraday" = specific time window,
#             "multi_day" = entire date range.
# ---------------------------------------------------------------------------
EVENTS_2026: list[dict[str, Any]] = [
    # ── July ────────────────────────────────────────────────────────────────
    {
        "date": "2026-07-08",
        "time_et": "15:00",
        "name": "Fed Minutes (June 16-17 FOMC)",
        "impact": "medium",
        "veto_type": "intraday",
        "caution_window_start": "14:30",
        "caution_window_end": "16:00",
        "source": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
        "notes": "Minutes can reprice rate-cut expectations. Avoid new short premium 14:30–16:00.",
    },
    {
        "date": "2026-07-08",
        "time_et": "13:00",
        "name": "Treasury 10Y Note Reopening Auction",
        "impact": "medium",
        "veto_type": "intraday",
        "caution_window_start": "12:30",
        "caution_window_end": "13:30",
        "source": "https://home.treasury.gov/system/files/221/Tentative-Auction-Schedule.pdf",
        "notes": "Weak demand can spike yields and pressure equities. Avoid adding risk around auction.",
    },
    {
        "date": "2026-07-09",
        "time_et": "13:00",
        "name": "Treasury 30Y Bond Reopening Auction",
        "impact": "medium",
        "veto_type": "intraday",
        "caution_window_start": "12:30",
        "caution_window_end": "13:30",
        "source": "https://home.treasury.gov/system/files/221/Tentative-Auction-Schedule.pdf",
        "notes": "30Y bond auctions drive long-end yield volatility. Size down during window.",
    },
    {
        "date": "2026-07-14",
        "time_et": "08:30",
        "name": "CPI Release (June 2026)",
        "impact": "high",
        "veto_type": "pre_event",
        "caution_window_start": "00:00",
        "caution_window_end": "09:30",
        "source": "https://www.bls.gov/schedule/news_release/cpi.htm",
        "notes": "High-impact binary event. No new short premium before release. Long directional only after confirmed post-release direction.",
    },
    {
        "date": "2026-07-28",
        "time_et": "all_day",
        "name": "FOMC Meeting Day 1",
        "impact": "high",
        "veto_type": "multi_day",
        "caution_window_start": "00:00",
        "caution_window_end": "23:59",
        "source": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
        "notes": "FOMC day 1: elevated uncertainty. No new short premium. Reduce size.",
    },
    {
        "date": "2026-07-29",
        "time_et": "14:00",
        "name": "FOMC Decision + Powell Press Conference",
        "impact": "high",
        "veto_type": "multi_day",
        "caution_window_start": "00:00",
        "caution_window_end": "23:59",
        "source": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
        "notes": "Fed day: binary event. Stand aside before 14:00. Post-decision direction only after market confirmation.",
    },
    {
        "date": "2026-07-30",
        "time_et": "08:30",
        "name": "GDP Advance Estimate Q2 2026",
        "impact": "high",
        "veto_type": "pre_event",
        "caution_window_start": "00:00",
        "caution_window_end": "09:30",
        "source": "https://www.bea.gov/news/schedule",
        "notes": "GDP miss or beat moves macro expectations significantly. No pre-event short premium.",
    },
    {
        "date": "2026-07-30",
        "time_et": "08:30",
        "name": "PCE Price Index / Personal Income & Outlays",
        "impact": "high",
        "veto_type": "pre_event",
        "caution_window_start": "00:00",
        "caution_window_end": "09:30",
        "source": "https://www.bea.gov/data/personal-consumption-expenditures-price-index",
        "notes": "Fed's preferred inflation gauge. Same-day as GDP. Double binary event.",
    },
    # ── August placeholder (extend as calendar becomes available) ───────────
    {
        "date": "2026-08-12",
        "time_et": "08:30",
        "name": "CPI Release (July 2026) — tentative",
        "impact": "high",
        "veto_type": "pre_event",
        "caution_window_start": "00:00",
        "caution_window_end": "09:30",
        "source": "https://www.bls.gov/schedule/news_release/cpi.htm",
        "notes": "Tentative. Confirm on BLS schedule closer to date.",
    },
]


def events_for_date(d: date) -> list[dict[str, Any]]:
    ds = d.isoformat()
    return [e for e in EVENTS_2026 if e["date"] == ds]


def risk_window_for_date(d: date) -> dict[str, Any]:
    events = events_for_date(d)
    if not events:
        return {
            "max_impact": "none",
            "vetoes": [],
            "caution_windows": [],
            "allowed_playbooks": ["directional_long", "directional_short", "short_premium", "stand_aside"],
            "events": [],
        }
    max_impact = "none"
    for e in events:
        if e["impact"] == "high":
            max_impact = "high"
        elif e["impact"] == "medium" and max_impact != "high":
            max_impact = "medium"
        elif e["impact"] == "low" and max_impact == "none":
            max_impact = "low"

    vetoes: list[str] = []
    caution_windows: list[dict] = []

    for e in events:
        if e["impact"] == "high":
            vetoes.append("new_short_premium_blocked")
            vetoes.append("size_down_required")
        elif e["impact"] == "medium":
            if "size_down_required" not in vetoes:
                vetoes.append("size_down_required")
        if e.get("caution_window_start") and e.get("caution_window_end"):
            caution_windows.append({
                "name": e["name"],
                "start_et": e["caution_window_start"],
                "end_et": e["caution_window_end"],
                "impact": e["impact"],
            })

    vetoes = sorted(set(vetoes))
    allowed: list[str] = ["stand_aside"]
    if "new_short_premium_blocked" not in vetoes:
        allowed.append("short_premium")
    if max_impact != "high":
        allowed.extend(["directional_long", "directional_short"])
    else:
        allowed.append("directional_long_post_confirmation")

    return {
        "max_impact": max_impact,
        "vetoes": vetoes,
        "caution_windows": caution_windows,
        "allowed_playbooks": allowed,
        "events": [{"name": e["name"], "time_et": e["time_et"], "impact": e["impact"]} for e in events],
    }


def _dynamic_risk(today: date, now: datetime, path: Path = DYNAMIC_RISK_PATH) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        generated = datetime.fromisoformat(str(payload["generated_at"]).replace("Z", "+00:00"))
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    age_seconds = max(0.0, (now - generated).total_seconds())
    if str(payload.get("date")) != today.isoformat() or age_seconds > 45 * 60:
        return None
    return {**payload, "age_seconds": round(age_seconds)}


def _merge_dynamic_risk(window: dict[str, Any], dynamic: dict[str, Any] | None) -> dict[str, Any]:
    if not dynamic or dynamic.get("risk_level") not in {"medium", "high"}:
        return window
    merged = dict(window)
    level = str(dynamic["risk_level"])
    if level == "high":
        merged["max_impact"] = "high"
        merged["allowed_playbooks"] = ["stand_aside"]
    elif merged.get("max_impact") == "none":
        merged["max_impact"] = "medium"
    merged["vetoes"] = sorted(set(merged.get("vetoes") or []).union(dynamic.get("vetoes") or []))
    merged["events"] = list(merged.get("events") or []) + [{
        "name": "Dynamic geopolitical/news risk",
        "time_et": "intraday",
        "impact": level,
    }]
    merged["dynamic_risk"] = {
        "risk_level": level,
        "recommended_posture": dynamic.get("recommended_posture"),
        "evidence_count": len(dynamic.get("evidence") or []),
        "max_evidence_score": dynamic.get("max_evidence_score"),
        "age_seconds": dynamic.get("age_seconds"),
    }
    return merged


def build_report(
    today: date | None = None,
    *,
    now: datetime | None = None,
    dynamic_risk_path: Path = DYNAMIC_RISK_PATH,
) -> dict[str, Any]:
    today = today or date.today()
    now = now or datetime.now(timezone.utc)
    dynamic = _dynamic_risk(today, now, dynamic_risk_path)
    today_window = _merge_dynamic_risk(risk_window_for_date(today), dynamic)
    today_window["date"] = today.isoformat()

    upcoming = []
    for offset in range(1, 6):
        d = today + timedelta(days=offset)
        w = risk_window_for_date(d)
        w["date"] = d.isoformat()
        upcoming.append(w)

    high_days = [w["date"] for w in [today_window] + upcoming if w["max_impact"] == "high"]

    return {
        "provider": "market_catalyst_calendar",
        "mode": "read_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "today": today_window,
        "upcoming": upcoming,
        "high_impact_days_ahead": high_days,
        "warnings": [
            "Read-only macro calendar. Hardcoded 2026 events — verify against official sources before each event.",
            "Do not use this as a trade trigger. Use only as a veto and caution context layer.",
            "No broker calls. No orders. No settings changes.",
        ],
    }


def write_report(report: dict[str, Any], path: Path = REPORT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def append_log(report: dict[str, Any], log_path: Path = LOG_PATH) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")


def print_report(report: dict[str, Any]) -> None:
    today = report["today"]
    print("\nMarket Catalyst Calendar | read-only")
    print("=" * 72)
    print(f"date={today['date']} impact={today['max_impact']} vetoes={today['vetoes']}")
    for e in today.get("events", []):
        print(f"  {e['time_et']} ET  [{e['impact'].upper()}]  {e['name']}")
    if today.get("caution_windows"):
        for w in today["caution_windows"]:
            print(f"  caution: {w['start_et']}–{w['end_et']} ET — {w['name']}")
    print(f"  allowed: {today['allowed_playbooks']}")
    print("\nUpcoming (5 days):")
    for w in report["upcoming"]:
        if w["max_impact"] != "none":
            print(f"  {w['date']}  [{w['max_impact'].upper()}]  {[e['name'] for e in w['events']]}")
    if report["high_impact_days_ahead"]:
        print(f"\nHigh-impact days ahead: {report['high_impact_days_ahead']}")
    print("\nNo orders placed. No execution settings changed.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Market catalyst calendar — read-only.")
    parser.add_argument("--date", default=None)
    parser.add_argument("--print", action="store_true", dest="do_print")
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    args = parser.parse_args()

    today = date.fromisoformat(args.date) if args.date else date.today()
    report = build_report(today=today)
    write_report(report, args.report_path)
    append_log(report, args.log_path)
    if args.do_print:
        print_report(report)
    else:
        print(f"Market catalyst calendar written to {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
