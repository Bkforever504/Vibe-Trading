#!/usr/bin/env python3
"""Render the latest read-only algo evidence into an auditable monthly packet."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "data" / "opportunity_intelligence_report.json"


def _text(value: Any) -> str:
    return "n/a" if value is None else str(value)


def render_packet(report: dict[str, Any]) -> str:
    generated = str(report.get("generated_at") or datetime.now(timezone.utc).isoformat())
    month = generated[:7]
    lines = [
        f"# Algorithm Operations Evidence Packet - {month}",
        "",
        f"Generated: {generated}",
        "",
        "## Authority",
        "",
        f"- Execution enabled: `{bool(report.get('execution_enabled'))}`",
        f"- Can submit orders: `{bool(report.get('can_submit_orders'))}`",
        f"- Orders submitted: `{int(report.get('orders_submitted') or 0)}`",
        f"- Promotion authority: `{_text(report.get('promotion_authority'))}`",
        "",
        "## Strategy Lifecycle",
        "",
        "| Lane | State | N | Stable reviews | Paper review eligible | Reasons |",
        "|---|---|---:|---:|---|---|",
    ]
    lifecycle = ((report.get("strategy_lifecycle") or {}).get("lanes") or {})
    for lane, row in sorted(lifecycle.items()):
        reasons = ", ".join(row.get("reasons") or []) or "none"
        lines.append(
            f"| {lane} | {row.get('state')} | {row.get('observations')} | "
            f"{row.get('stable_review_streak')}/{row.get('stable_reviews_required')} | "
            f"{row.get('paper_review_eligible')} | {reasons} |"
        )

    lines.extend([
        "",
        "## Edge Evidence",
        "",
        "| Lane | N | Mean PnL | Profit factor | Placebo | Decay | Bootstrap 90% |",
        "|---|---:|---:|---:|---|---|---|",
    ])
    for lane, row in sorted((report.get("evidence") or {}).items()):
        ci = (row.get("bootstrap") or {}).get("ci90") or [None, None]
        lines.append(
            f"| {lane} | {row.get('observations')} | {_text(row.get('mean_pnl'))} | "
            f"{_text(row.get('profit_factor'))} | {(row.get('placebo') or {}).get('status')} | "
            f"{(row.get('decay') or {}).get('status')} | [{_text(ci[0])}, {_text(ci[1])}] |"
        )

    dependence = report.get("portfolio_dependence") or {}
    lines.extend([
        "",
        "## Portfolio Dependence",
        "",
        f"Status: `{dependence.get('status', 'unknown')}`",
        "",
        "| Pair | Overlap | Return corr | Loss-event corr | Joint-loss lift | Status |",
        "|---|---:|---:|---:|---:|---|",
    ])
    for row in dependence.get("pairs") or []:
        lines.append(
            f"| {row.get('left')} / {row.get('right')} | {row.get('overlap')} | "
            f"{_text(row.get('return_correlation'))} | {_text(row.get('loss_event_correlation'))} | "
            f"{_text(row.get('joint_loss_lift_vs_independence'))} | {row.get('status')} |"
        )

    execution = report.get("execution_reality_gap") or {}
    lines.extend([
        "",
        "## Execution Reality",
        "",
        f"- Status: `{execution.get('status', 'unknown')}`",
        f"- Forward fill samples: `{execution.get('signal_slippage_samples', 0)}`",
        f"- Modeled mid-to-executable gap: `{_text(execution.get('modeled_mid_to_executable_gap_pct'))}%`",
        f"- Observed average adverse fill versus signal ask: `{_text(execution.get('average_adverse_fill_vs_signal_ask_pct'))}%`",
        f"- Observed p95 adverse fill versus signal ask: `{_text(execution.get('p95_adverse_fill_vs_signal_ask_pct'))}%`",
        "",
        "## Reproducibility",
        "",
        f"- Configuration fingerprint: `{(report.get('configuration_fingerprint') or {}).get('combined', 'missing')}`",
        f"- Operational SLO: `{(report.get('operational_slo') or {}).get('status', 'unknown')}`",
        "",
        "This packet is descriptive. It cannot place orders, promote a strategy, reactivate a suspended strategy, or increase risk.",
        "",
    ])
    return "\n".join(lines)


def write_packet(report: dict[str, Any], out_dir: Path) -> Path:
    month = str(report.get("generated_at") or datetime.now(timezone.utc).isoformat())[:7]
    path = out_dir / f"monthly_algo_evidence_{month}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_packet(report), encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out-dir", type=Path, default=ROOT / "data")
    args = parser.parse_args()
    report = json.loads(args.source.read_text(encoding="utf-8"))
    if report.get("execution_enabled") or report.get("can_submit_orders") or report.get("orders_submitted"):
        raise ValueError("Evidence packet source violates read-only authority invariants")
    print(write_packet(report, args.out_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
