"""Read-only exposure posture coach.

Converts Market Force, breadth, and distribution-day evidence into an advisory
operating posture. This never changes bot settings automatically.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
LOG_PATH = ROOT / "data" / "exposure_coach_log.jsonl"
REPORT_PATH = VIBE_HOME / "reports" / "exposure-coach.json"

SOURCE_PATHS = {
    "market_force": ROOT / "data" / "market_force_score_log.jsonl",
    "breadth": ROOT / "data" / "market_breadth_uptrend_log.jsonl",
    "distribution": ROOT / "data" / "distribution_day_log.jsonl",
}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def latest_for_day(path: Path, day: str) -> dict[str, Any] | None:
    rows = [row for row in _read_jsonl(path) if str(row.get("date", ""))[:10] == day]
    return rows[-1] if rows else None


def derive_posture(market_force: dict[str, Any] | None, breadth: dict[str, Any] | None, distribution: dict[str, Any] | None) -> dict[str, Any]:
    reasons: list[str] = []
    score = 0.0
    if market_force:
        mf_score = float(market_force.get("total_score") or 0.0)
        score += mf_score
        reasons.append(f"Market Force {market_force.get('classification')} score={mf_score}")
        if (market_force.get("risk_veto") or {}).get("active"):
            return _posture("cash_priority", 0.0, reasons + ["risk veto active"])
    else:
        reasons.append("Market Force missing")

    breadth_row = breadth.get("breadth") if isinstance(breadth, dict) and isinstance(breadth.get("breadth"), dict) else {}
    uptrend = str(breadth_row.get("uptrend_status") or "")
    if uptrend == "confirmed_uptrend":
        score += 2.0
        reasons.append("breadth confirmed uptrend")
    elif uptrend == "uptrend_under_pressure":
        score += 0.5
        reasons.append("breadth uptrend under pressure")
    elif uptrend == "correction":
        score -= 2.0
        reasons.append("breadth correction")
    elif not uptrend:
        reasons.append("breadth missing")

    distribution_agg = distribution.get("aggregate") if isinstance(distribution, dict) and isinstance(distribution.get("aggregate"), dict) else {}
    dist_regime = str(distribution_agg.get("regime") or "")
    if dist_regime == "severe":
        score -= 2.0
        reasons.append("severe distribution pressure")
    elif dist_regime == "high":
        score -= 1.25
        reasons.append("high distribution pressure")
    elif dist_regime == "caution":
        score -= 0.5
        reasons.append("distribution caution")

    if score >= 5:
        return _posture("aggressive", score, reasons)
    if score >= 2:
        return _posture("normal", score, reasons)
    if score >= -1:
        return _posture("cautious", score, reasons)
    return _posture("cash_priority", score, reasons)


def _posture(posture: str, score: float, reasons: list[str]) -> dict[str, Any]:
    settings = {
        "aggressive": {
            "risk_multiplier": 1.0,
            "new_trade_bias": "allow best setups only",
            "notes": "Full paper risk budget allowed, still subject to execution guard.",
        },
        "normal": {
            "risk_multiplier": 0.75,
            "new_trade_bias": "allow high-confidence setups",
            "notes": "Prefer aligned trend/force setups; avoid marginal entries.",
        },
        "cautious": {
            "risk_multiplier": 0.5,
            "new_trade_bias": "paper only, require extra confirmation",
            "notes": "Do not expand exposure; use scanners to learn.",
        },
        "cash_priority": {
            "risk_multiplier": 0.0,
            "new_trade_bias": "avoid new discretionary exposure",
            "notes": "Let existing guarded positions manage; no new gates are changed automatically.",
        },
    }[posture]
    return {
        "posture": posture,
        "score": round(score, 3),
        "advisory_settings": settings,
        "reasons": reasons,
    }


def build_report(day: str | None = None, paths: dict[str, Path] | None = None) -> dict[str, Any]:
    day = day or date.today().isoformat()
    paths = paths or SOURCE_PATHS
    rows = {name: latest_for_day(path, day) for name, path in paths.items()}
    posture = derive_posture(rows["market_force"], rows["breadth"], rows["distribution"])
    return {
        "date": day,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "exposure_coach",
        "mode": "read_only",
        "execution_enabled": False,
        **posture,
        "source_paths": {name: str(path) for name, path in paths.items()},
        "warnings": [
            "Advisory only. This does not modify bot risk settings or place orders.",
            "Use after 30-day outcome review before considering any automated gate.",
        ],
    }


def append_log(report: dict[str, Any], log_path: Path = LOG_PATH) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report, separators=(",", ":")) + "\n")


def write_report(report: dict[str, Any], report_path: Path = REPORT_PATH) -> Path:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report_path


def print_report(report: dict[str, Any]) -> None:
    print("\nExposure Coach | read-only")
    print("=" * 72)
    print(f"posture={report['posture']} score={report['score']} risk_mult={report['advisory_settings']['risk_multiplier']}")
    for reason in report["reasons"]:
        print(f"- {reason}")
    print("No settings changed. No orders placed.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build read-only exposure posture advice.")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_output")
    args = parser.parse_args()
    report = build_report(day=args.date)
    append_log(report, args.log_path)
    write_report(report, args.report_path)
    if args.print_output:
        print_report(report)
    else:
        print(f"Exposure coach logged to {args.log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
