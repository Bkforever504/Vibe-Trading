#!/usr/bin/env python3
"""Daily report card for bots, shadow loggers, and read-only scanners.

This grades observability and evidence maturity. It is not an execution gate and
does not change any strategy settings.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import signal_stack_leaderboard as leaderboard

VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_DIR = VIBE_HOME / "reports"
REPORT_PATH = REPORT_DIR / "signal-stack-grades.json"
CSV_PATH = REPORT_DIR / "signal-stack-grades.csv"
LOG_PATH = ROOT / "data" / "signal_stack_grades_log.jsonl"

PROMOTION_SAMPLE_TARGET = 10
MATURE_SAMPLE_TARGET = 30


def _grade_letter(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def _freshness_points(status: str) -> tuple[float, str]:
    if status == "fresh":
        return 30.0, "fresh"
    if status == "aging":
        return 18.0, "aging"
    if status == "stale":
        return 8.0, "stale"
    return 0.0, "missing"


def _maturity_stage(sample_count: int, signal_count: int) -> str:
    if sample_count <= 0:
        return "no_data"
    if sample_count < PROMOTION_SAMPLE_TARGET:
        return "log_building"
    if signal_count < PROMOTION_SAMPLE_TARGET:
        return "needs_more_signals"
    if sample_count < MATURE_SAMPLE_TARGET:
        return "review_eligible"
    return "mature"


def _sample_points(sample_count: int, signal_count: int) -> float:
    row_points = min(sample_count, MATURE_SAMPLE_TARGET) / MATURE_SAMPLE_TARGET * 20.0
    signal_points = min(signal_count, PROMOTION_SAMPLE_TARGET) / PROMOTION_SAMPLE_TARGET * 15.0
    return row_points + signal_points


def _confidence_points(avg_confidence: Any) -> float:
    if not isinstance(avg_confidence, (int, float)):
        return 5.0
    return max(0.0, min(10.0, float(avg_confidence))) / 10.0 * 15.0


def _quality_points(item: dict[str, Any]) -> tuple[float, list[str]]:
    notes: list[str] = []
    points = 20.0
    bad_lines = int(item.get("bad_json_lines") or 0)
    if bad_lines:
        points -= min(10.0, bad_lines * 2.0)
        notes.append(f"bad_json_lines={bad_lines}")
    if item.get("freshness", {}).get("status") in {"missing", "stale"}:
        points -= 5.0
    blocked = int(item.get("blocked_count") or 0)
    if blocked:
        points -= min(8.0, blocked * 0.5)
        notes.append(f"guard_blocks={blocked}")
    pnl = item.get("total_pnl")
    if isinstance(pnl, (int, float)) and pnl < 0:
        points -= min(8.0, abs(float(pnl)) / 1000.0)
        notes.append("negative_pnl")
    return max(0.0, points), notes


def _post_config_grade(post_config: dict[str, Any]) -> str:
    sample_count = int(post_config.get("sample_count") or 0)
    total_pnl = post_config.get("total_pnl")
    win_rate = post_config.get("win_rate")
    max_drawdown = post_config.get("max_drawdown_dollars")
    score = 50.0
    if isinstance(total_pnl, (int, float)) and total_pnl > 0:
        score += 20.0
    if isinstance(win_rate, (int, float)):
        score += max(0.0, min(1.0, float(win_rate))) * 20.0
    score += min(sample_count, PROMOTION_SAMPLE_TARGET) / PROMOTION_SAMPLE_TARGET * 10.0
    if isinstance(max_drawdown, (int, float)) and max_drawdown < 0:
        score -= min(20.0, abs(float(max_drawdown)) / 500.0)
    if sample_count < PROMOTION_SAMPLE_TARGET:
        score = min(score, 85.0)
    return _grade_letter(score)


def _ops_score(item: dict[str, Any]) -> float:
    freshness = item.get("freshness") if isinstance(item.get("freshness"), dict) else {}
    status = str(freshness.get("status") or "missing")
    score = 0.0
    if status == "fresh":
        score += 55.0
    elif status == "aging":
        score += 35.0
    elif status == "stale":
        score += 15.0
    if int(item.get("sample_count") or 0) > 0:
        score += 25.0
    bad_lines = int(item.get("bad_json_lines") or 0)
    score += max(0.0, 20.0 - bad_lines * 5.0)
    return round(max(0.0, min(100.0, score)), 1)


def grade_item(item: dict[str, Any]) -> dict[str, Any]:
    freshness = item.get("freshness") if isinstance(item.get("freshness"), dict) else {}
    freshness_score, freshness_label = _freshness_points(str(freshness.get("status") or "missing"))
    sample_count = int(item.get("sample_count") or 0)
    signal_count = int(item.get("signal_count") or 0)
    sample_score = _sample_points(sample_count, signal_count)
    confidence_score = _confidence_points(item.get("avg_confidence"))
    quality_score, quality_notes = _quality_points(item)
    evidence_score = round(max(0.0, min(100.0, freshness_score + sample_score + confidence_score + quality_score)), 1)
    ops_score = _ops_score(item)
    maturity = _maturity_stage(sample_count, signal_count)
    category = str(item.get("category") or "")
    mode = str(item.get("execution_mode") or "unknown")
    warnings = list(quality_notes)
    if maturity in {"no_data", "log_building"}:
        warnings.append("not_enough_samples")
    elif maturity == "needs_more_signals":
        warnings.append("needs_more_signal_events")
    if category == "context_scanner" or category.endswith("context"):
        warnings.append("context_only")
    if "live" in mode:
        warnings.append("execution_capable_review_separately")
    post_config = item.get("post_config") if isinstance(item.get("post_config"), dict) else None
    if post_config and item.get("total_pnl") != post_config.get("total_pnl"):
        warnings.append("all_time_includes_pre_config_artifact")
        post_config = dict(post_config)
        post_config["grade"] = _post_config_grade(post_config)
    return {
        "name": item.get("name"),
        "category": category,
        "mode": mode,
        "grade": _grade_letter(evidence_score),
        "score": evidence_score,
        "ops_grade": _grade_letter(ops_score),
        "ops_score": ops_score,
        "evidence_grade": _grade_letter(evidence_score),
        "evidence_score": evidence_score,
        "freshness": freshness_label,
        "sample_count": sample_count,
        "signal_count": signal_count,
        "avg_confidence": item.get("avg_confidence"),
        "total_pnl": item.get("total_pnl"),
        "win_rate": item.get("win_rate"),
        "max_drawdown_dollars": item.get("max_drawdown_dollars"),
        "maturity_stage": maturity,
        "promotion_ready": maturity in {"review_eligible", "mature"} and evidence_score >= 80,
        "warnings": warnings,
        "source_path": item.get("source_path"),
        "post_config": post_config,
    }


def build_report(now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    source = leaderboard.build_leaderboard(now)
    grades = [grade_item(item) for item in source["items"]]
    grades.sort(key=lambda row: (row["ops_score"], row["evidence_score"], row["sample_count"], row["signal_count"]), reverse=True)
    by_grade: dict[str, int] = {}
    by_stage: dict[str, int] = {}
    for row in grades:
        by_grade[row["grade"]] = by_grade.get(row["grade"], 0) + 1
        by_stage[row["maturity_stage"]] = by_stage.get(row["maturity_stage"], 0) + 1
    return {
        "date": now.date().isoformat(),
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "provider": "signal_stack_grades",
        "mode": "read_only",
        "execution_enabled": False,
        "item_count": len(grades),
        "by_grade": by_grade,
        "by_ops_grade": dict(sorted(Counter(row["ops_grade"] for row in grades).items())),
        "by_maturity_stage": by_stage,
        "promotion_ready_count": sum(1 for row in grades if row["promotion_ready"]),
        "items": grades,
        "warnings": [
        "Ops grade measures whether a component is logging cleanly today.",
        "Evidence grade measures sample maturity and signal usefulness.",
            "A high grade is not a live-trading approval.",
            "Execution promotion still requires rules/signal_promotion_rules.md.",
        ],
    }


def write_json(report: dict[str, Any], path: Path = REPORT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return path


def append_log(report: dict[str, Any], path: Path = LOG_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report, separators=(",", ":"), default=str) + "\n")
    return path


def write_csv(report: dict[str, Any], path: Path = CSV_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "name", "category", "mode", "ops_grade", "ops_score", "evidence_grade", "evidence_score", "grade", "score", "freshness",
        "sample_count", "signal_count", "avg_confidence", "total_pnl",
        "win_rate", "max_drawdown_dollars", "maturity_stage",
        "promotion_ready", "post_config", "warnings", "source_path",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in report["items"]:
            out = {key: row.get(key, "") for key in fieldnames}
            if isinstance(out.get("post_config"), dict):
                out["post_config"] = json.dumps(out["post_config"], separators=(",", ":"), default=str)
            out["warnings"] = ",".join(row.get("warnings") or [])
            writer.writerow(out)
    return path


def print_report(report: dict[str, Any]) -> None:
    print("\nSignal Stack Grades | read-only")
    print("=" * 96)
    print(
        f"items={report['item_count']} ops={report['by_ops_grade']} evidence={report['by_grade']} "
        f"stages={report['by_maturity_stage']} promotion_ready={report['promotion_ready_count']}"
    )
    print()
    for row in report["items"]:
        conf = "-" if row.get("avg_confidence") is None else f"{float(row['avg_confidence']):.1f}"
        print(
            f"{row['name']:<26} ops={row['ops_grade']:<2} {row['ops_score']:>5.1f} "
            f"evidence={row['evidence_grade']:<2} {row['evidence_score']:>5.1f} "
            f"fresh={row['freshness']:<7} rows={row['sample_count']:<3} "
            f"signals={row['signal_count']:<3} conf={conf:<4} stage={row['maturity_stage']}"
        )
        post_config = row.get("post_config")
        if isinstance(post_config, dict):
            print(
                f"{'':<26} post_config={post_config.get('grade', '-'):<2} "
                f"from={post_config.get('start_date', '-')} rows={post_config.get('sample_count', 0):<3} "
                f"pnl=${float(post_config.get('total_pnl') or 0):,.2f} "
                f"wr={float(post_config.get('win_rate') or 0) * 100:.1f}% "
                f"label={post_config.get('label', '-')}"
            )
    print(f"\nJSON: {REPORT_PATH}")
    print(f"CSV:  {CSV_PATH}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--csv-path", type=Path, default=CSV_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    report = build_report()
    print_report(report)
    if not args.no_write:
        append_log(report, args.log_path)
        write_json(report, args.report_path)
        write_csv(report, args.csv_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
