"""Build JSON and HTML performance views for the Polymarket weather paper bot."""
from __future__ import annotations

import argparse
import html
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_PATH = Path.home() / ".vibe-trading" / "polymarket-weather-paper-state.json"
REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "polymarket-weather-performance.json"
HTML_PATH = Path.home() / ".vibe-trading" / "reports" / "polymarket-weather-dashboard.html"


def _read(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _city(slug: Any) -> str:
    match = re.match(r"highest-temperature-in-(.+?)-on-", str(slug or ""))
    return match.group(1).replace("-", " ").title() if match else "Unknown"


def _lead_bucket(hours: Any) -> str:
    try:
        value = float(hours)
    except (TypeError, ValueError):
        return "unknown"
    return "under_6h" if value < 6 else "6_to_12h" if value < 12 else "12_to_24h" if value < 24 else "over_24h"


def _stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    closed = [row for row in rows if row.get("exit_reason")]
    pnl = sum(float(row.get("pnl_dollars") or 0.0) for row in closed)
    risk = sum(float(row.get("risk_dollars") or 0.0) for row in closed)
    wins = sum(1 for row in closed if float(row.get("pnl_dollars") or 0.0) > 0)
    promotion_grade = sum(1 for row in closed if row.get("promotion_grade") is True)
    return {
        "closed_count": len(closed),
        "promotion_grade_closed_count": promotion_grade,
        "win_rate": round(wins / len(closed), 3) if closed else None,
        "net_pnl_dollars": round(pnl, 2),
        "return_on_risk": round(pnl / risk, 3) if risk else None,
        "avg_entry_edge": round(sum(float(row.get("entry_edge") or 0.0) for row in closed) / len(closed), 4) if closed else None,
    }


def build_report(state_path: Path = STATE_PATH) -> dict[str, Any]:
    state = _read(state_path)
    open_rows = list(state.get("positions") or [])
    closed_rows = list(state.get("closed_positions") or [])
    open_near_misses = list(state.get("near_miss_observations") or [])
    closed_near_misses = list(state.get("closed_near_miss_observations") or [])
    all_rows = open_rows + closed_rows
    by_city: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_lead: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in all_rows:
        by_city[_city(row.get("slug"))].append(row)
        by_lead[_lead_bucket(row.get("entry_lead_hours"))].append(row)
    return {
        "provider": "polymarket_weather_performance_report",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": "paper_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "open_count": len(open_rows),
        "closed_count": len(closed_rows),
        "promotion_grade_closed_count": sum(1 for row in closed_rows if row.get("promotion_grade") is True),
        "overall": _stats(closed_rows),
        "near_miss_research": {
            "edge_band": "5%_to_under_10%",
            "open_count": len(open_near_misses),
            "closed_count": len(closed_near_misses),
            "win_rate": round(sum(bool(row.get("would_win")) for row in closed_near_misses) / len(closed_near_misses), 3) if closed_near_misses else None,
            "hypothetical_net_pnl_dollars": round(sum(float(row.get("hypothetical_pnl_dollars") or 0.0) for row in closed_near_misses), 2),
            "threshold_change_allowed": False,
        },
        "by_city": {name: _stats(rows) for name, rows in sorted(by_city.items())},
        "by_lead_time": {name: _stats(rows) for name, rows in sorted(by_lead.items())},
        "evidence_status": "eligible_for_live_review" if sum(1 for row in closed_rows if row.get("promotion_grade") is True) >= 200 else "insufficient_paper_evidence",
        "warnings": ["Only three-model-agreement positions are promotion grade.", "Near-miss outcomes are research-only and cannot change the 10% threshold automatically.", "Live execution remains disabled and requires explicit approval after 200+ completed paper signals."],
    }


def write_report(report: dict[str, Any], json_path: Path = REPORT_PATH, html_path: Path = HTML_PATH) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rows = []
    for city, stats in report["by_city"].items():
        win_rate = "--" if stats["win_rate"] is None else f"{stats['win_rate']:.1%}"
        return_on_risk = "--" if stats["return_on_risk"] is None else f"{stats['return_on_risk']:.1%}"
        rows.append(f"<tr><td>{html.escape(city)}</td><td>{stats['closed_count']}</td><td>{stats['promotion_grade_closed_count']}</td><td>{win_rate}</td><td>${stats['net_pnl_dollars']:.2f}</td><td>{return_on_risk}</td></tr>")
    body = f"""<!doctype html><html><head><meta charset='utf-8'><title>Polymarket Weather Paper Bot</title><style>body{{font:14px system-ui;margin:32px;color:#17202a}}h1{{font-size:24px}}.status{{padding:10px;border-left:4px solid #148f77;background:#eef8f5}}table{{border-collapse:collapse;width:100%;margin-top:20px}}th,td{{padding:9px;border-bottom:1px solid #d5d8dc;text-align:left}}th{{background:#f4f6f7}}</style></head><body><h1>Polymarket Weather Paper Bot</h1><p class='status'>Mode: paper only | Open: {report['open_count']} | Closed: {report['closed_count']} | Promotion-grade: {report['promotion_grade_closed_count']} | {html.escape(report['evidence_status'])}</p><table><thead><tr><th>City</th><th>Closed</th><th>Qualified</th><th>Win rate</th><th>Net P&amp;L</th><th>Return on risk</th></tr></thead><tbody>{''.join(rows) or '<tr><td colspan=6>No completed paper positions yet.</td></tr>'}</tbody></table></body></html>"""
    html_path.write_text(body, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-path", type=Path, default=STATE_PATH)
    parser.add_argument("--json-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--html-path", type=Path, default=HTML_PATH)
    args = parser.parse_args()
    report = build_report(args.state_path)
    write_report(report, args.json_path, args.html_path)
    print(f"Polymarket weather performance report written to {args.json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
