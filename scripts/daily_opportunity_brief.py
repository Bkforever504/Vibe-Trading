#!/usr/bin/env python3
"""Create source-labeled premarket, intraday, or EOD opportunity briefs."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPORT_DIR = Path.home() / ".vibe-trading" / "reports"
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.market_data_provider_registry import build_provider_registry


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def build_brief(*, period: str = "premarket", report_dir: Path = REPORT_DIR, root: Path = ROOT) -> dict[str, Any]:
    opportunity = _read(report_dir / "live-opportunity-engine.json")
    radar = _read(report_dir / "intraday-opportunity-radar.json")
    sec = _read(report_dir / "sec-catalyst-feed.json")
    calendar = _read(report_dir / "market-catalyst-calendar.json")
    intelligence = _read(root / "data" / "opportunity_intelligence_report.json")
    candidates = [row for row in opportunity.get("candidates") or [] if isinstance(row, dict)]
    ready = [row for row in candidates if row.get("state") == "READY_TO_REVIEW"]
    rejected = [row for row in candidates if row.get("state") == "REJECT"]
    decision = "READY_TO_REVIEW" if ready else "STAND_ASIDE"
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "period": period,
        "decision_state": decision,
        "top_research_priorities": ready[:3] if ready else candidates[:3],
        "rejection_summary": {
            "count": len(rejected),
            "reasons": sorted({reason for row in rejected for reason in row.get("blockers") or []}),
        },
        "fresh_sec_catalysts": [row for row in sec.get("catalysts") or [] if isinstance(row, dict)][:20],
        "macro_calendar": {
            "today": calendar.get("today"),
            "high_impact_days_ahead": calendar.get("high_impact_days_ahead") or [],
        },
        "coverage": radar.get("coverage") or {},
        "feed": opportunity.get("feed") or {},
        "validation": {
            "promotion_authority": intelligence.get("promotion_authority", "blocked"),
            "strategy_lifecycle": intelligence.get("strategy_lifecycle") or {},
            "configuration_fingerprint": intelligence.get("configuration_fingerprint") or {},
        },
        "providers": build_provider_registry(root=root),
        "manual_checklist": [
            "Confirm quote age and feed provenance",
            "Confirm completed-bar trigger and invalidation",
            "Confirm spread, liquidity, and post-friction reward/risk",
            "Confirm catalyst and market/sector alignment",
            "Stand aside when any required source is stale or missing",
        ],
        "warnings": [
            "A research priority is not a final trade recommendation.",
            "No order can originate from this briefing.",
        ],
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# {str(report.get('period') or 'daily').title()} Opportunity Brief",
        "",
        f"Generated: {report.get('generated_at')}",
        f"Decision state: **{report.get('decision_state', 'STAND_ASIDE')}**",
        "",
        "## Top research priorities",
    ]
    rows = report.get("top_research_priorities") or []
    if not rows:
        lines.append("- None. Stand aside until a fresh, fully specified setup appears.")
    for row in rows:
        target = ((row.get("targets") or [{}])[0] or {}).get("price")
        lines.append(
            f"- **{row.get('symbol')}** {str(row.get('setup_family') or '').replace('_', ' ')}: "
            f"entry {row.get('entry')}, invalidation {row.get('invalidation')}, target {target}, "
            f"post-cost RR {row.get('reward_risk_after_friction')}, grade {row.get('grade')}."
        )
    lines.extend(["", "## Manual checklist"])
    lines.extend(f"- {item}" for item in report.get("manual_checklist") or [])
    lines.extend(["", "Read-only research. Manual review only. No order authority.", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--period", choices=("premarket", "intraday", "eod"), default="premarket")
    parser.add_argument("--report-dir", type=Path, default=REPORT_DIR)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = build_brief(period=args.period, report_dir=args.report_dir)
    json_out = args.json_out or args.report_dir / f"{args.period}-opportunity-brief.json"
    markdown_out = args.markdown_out or args.report_dir / f"{args.period}-opportunity-brief.md"
    json_out.parent.mkdir(parents=True, exist_ok=True)
    markdown_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_out.write_text(render_markdown(report), encoding="utf-8")
    if args.print_report:
        print(render_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
