#!/usr/bin/env python3
"""Verify market-session task timing and ordering.

Read-only governance script. It checks Windows Task Scheduler against the
intended Central-time trading-day sequence so open/close/EOD jobs do not drift.
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
from collections import defaultdict
from datetime import date, datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_DIR = VIBE_HOME / "reports"
REPORT_PATH = REPORT_DIR / "market-schedule-alignment.json"
LOG_PATH = ROOT / "data" / "market_schedule_alignment_log.jsonl"

REGULAR_MARKET_OPEN_CT = "08:30"
REGULAR_MARKET_CLOSE_CT = "15:00"

EXPECTED_TASKS = {
    # Timing governance before the rest of the day starts.
    r"\VibeTrade\MarketScheduleAlignment": {"08:10", "19:58"},
    # Premarket context before regular cash open.
    r"\VibeTrade\SocialTrendingSymbolsScanner": {"08:20"},
    r"\VibeTrade\IntradayRiskRefresh": {"08:24"},
    r"\VibeTrade\PreOpenSentimentLogger": {"08:25"},
    # Open + early session.
    r"\Flip-Bot-Entry": {"08:35"},
    r"\VibeTrade\GEXScanner": {"08:35"},
    r"\VibeTrade\IVRScanner": {"08:35"},
    r"\VibeTrade\RVIVRegimeScanner": {"08:37"},
    r"\VibeTrade\HurstRegimeScanner": {"08:38"},
    r"\VibeTrade\OpeningRangeBreadthScanner": {"08:40"},
    # Regular-hours execution/watch.
    r"\Flip-Bot-Monitor": {"08:45"},
    r"\VibeTradingShadowScanner": {"09:30", "10:30", "11:30", "12:30", "13:30", "14:30"},
    r"\Flip-Bot-Trend-Entry": {
        "09:45", "10:00", "10:15", "10:30", "10:45", "11:00", "11:15", "11:30",
        "11:45", "12:00", "12:15", "12:30", "12:45", "13:00", "13:15", "13:30", "13:45",
    },
    r"\IWM-Bot-Entry": {"09:45"},
    r"\IWM-Bot-Monitor": {"10:00", "11:00", "12:00", "13:00", "14:00", "15:00"},
    r"\VibeTrade\PortfolioConcentrationMonitor": {"11:05"},
    # Close context after regular close.
    r"\RSI2ShadowLogger": {"15:20"},
    r"\KAMAShadowLogger": {"15:20"},
    r"\VibeTrade\WilliamsRShadowLogger": {"15:20"},
    r"\VibeTrade\TTMSqueezeShadowLogger": {"15:20"},
    r"\VibeTrade\WaveTrendShadowLogger": {"15:20"},
    r"\VibeTrade\SMCShadowLogger": {"15:20"},
    r"\VibeTrade\RelativeVolumeScanner": {"15:30"},
    r"\VibeTrade\MarketBreadthUptrendScanner": {"15:31"},
    r"\VibeTrade\DistributionDayScanner": {"15:32"},
    r"\VibeTrade\SectorRotationRanker": {"15:33"},
    r"\VibeTrade\SignalStackHealthReport": {"15:35"},
    r"\VibeTrade\MarketForceScore": {"15:40"},
    r"\VibeTrade\ExposureCoach": {"15:45"},
    # Evening review chain.
    r"\VibeTrade\SocialTrendingPersistenceReport": {"19:00"},
    r"\VibeTrade\OptionsLiquidityFeasibility": {"19:00"},
    r"\VibeTrade\FlipShadowPnLEvaluator": {"19:03"},
    r"\VibeTrade\SECInsiderBuyingScanner": {"19:05"},
    r"\VibeTrade\OptionsSurfaceIntelligence": {"19:05"},
    r"\VibeTrade\WeeklyHotInstrumentReport": {"19:08"},
    r"\VibeTrade\LimitlessMarketScanner": {"19:10"},
    r"\VibeTrade\DailyOptionsUniverseRanker": {"19:12"},
    r"\VibeTrade\ClosedTradePostmortem": {"19:15"},
    r"\VibeTrade\FlipBotLearningReport": {"19:19"},
    r"\VibeTrade\FlipExitQualityReport": {"19:17"},
    r"\VibeTrade\FlipFeatureAblationReport": {"19:18"},
    r"\VibeTrade\FlipEquityCurveReport": {"19:20"},
    r"\VibeTrade\SignalStackLeaderboard": {"19:20"},
    r"\VibeTrade\DailyBotActivityExport": {"19:25"},
    r"\VibeTrade\DailyOutcomeReviewer": {"19:30"},
    r"\VibeTrade\BotStatusSnapshot": {"19:35"},
    r"\VibeTrade\RegimeMemoryReport": {"19:40"},
    r"\VibeTrade\RejectedTradeIntelligence": {"19:45"},
    r"\VibeTrade\NeedsReviewQueue": {"19:50"},
    r"\VibeTrade\EdgeTrialLedgerReport": {"19:53"},
    r"\VibeTrade\SignalStackGrades": {"19:55"},
    r"\VibeTrade\LoopClosureReport": {"19:59"},
    r"\VibeTrade\DailyEODSummary": {"20:00"},
    r"\VibeTrade\EliteBotReadinessScorecard": {"20:03"},
    r"\VibeTrade\NightlyResearchLoop": {"20:05"},
}

ORDER_CHECKS = [
    ("preopen_before_open", r"\VibeTrade\PreOpenSentimentLogger", r"\Flip-Bot-Entry"),
    ("open_scanners_before_trend", r"\VibeTrade\OpeningRangeBreadthScanner", r"\Flip-Bot-Trend-Entry"),
    ("close_context_before_market_force", r"\VibeTrade\SectorRotationRanker", r"\VibeTrade\MarketForceScore"),
    ("activity_before_outcome", r"\VibeTrade\DailyBotActivityExport", r"\VibeTrade\DailyOutcomeReviewer"),
    ("liquidity_before_universe_rank", r"\VibeTrade\OptionsLiquidityFeasibility", r"\VibeTrade\DailyOptionsUniverseRanker"),
    ("surface_before_universe_rank", r"\VibeTrade\OptionsSurfaceIntelligence", r"\VibeTrade\DailyOptionsUniverseRanker"),
    ("weekly_context_before_universe_rank", r"\VibeTrade\WeeklyHotInstrumentReport", r"\VibeTrade\DailyOptionsUniverseRanker"),
    ("postmortem_before_exit_quality", r"\VibeTrade\ClosedTradePostmortem", r"\VibeTrade\FlipExitQualityReport"),
    ("postmortem_before_learning", r"\VibeTrade\ClosedTradePostmortem", r"\VibeTrade\FlipBotLearningReport"),
    ("exit_quality_before_feature_ablation", r"\VibeTrade\FlipExitQualityReport", r"\VibeTrade\FlipFeatureAblationReport"),
    ("exit_quality_before_equity_curve", r"\VibeTrade\FlipExitQualityReport", r"\VibeTrade\FlipEquityCurveReport"),
    ("trial_ledger_before_grades", r"\VibeTrade\EdgeTrialLedgerReport", r"\VibeTrade\SignalStackGrades"),
    ("grades_before_eod", r"\VibeTrade\SignalStackGrades", r"\VibeTrade\DailyEODSummary"),
    ("learning_before_loop_closure", r"\VibeTrade\FlipBotLearningReport", r"\VibeTrade\LoopClosureReport"),
    ("grades_before_loop_closure", r"\VibeTrade\SignalStackGrades", r"\VibeTrade\LoopClosureReport"),
    ("loop_closure_before_elite_scorecard", r"\VibeTrade\LoopClosureReport", r"\VibeTrade\EliteBotReadinessScorecard"),
    ("eod_before_elite_scorecard", r"\VibeTrade\DailyEODSummary", r"\VibeTrade\EliteBotReadinessScorecard"),
    ("equity_curve_before_elite_scorecard", r"\VibeTrade\FlipEquityCurveReport", r"\VibeTrade\EliteBotReadinessScorecard"),
    ("scorecard_before_nightly_loop", r"\VibeTrade\EliteBotReadinessScorecard", r"\VibeTrade\NightlyResearchLoop"),
    ("eod_before_nightly_loop", r"\VibeTrade\DailyEODSummary", r"\VibeTrade\NightlyResearchLoop"),
]


def _parse_time_to_minutes(value: str) -> int | None:
    text = str(value or "").strip()
    if not text or text.upper() == "N/A":
        return None
    try:
        dt = datetime.strptime(text, "%I:%M:%S %p")
        return dt.hour * 60 + dt.minute
    except ValueError:
        pass
    try:
        dt = datetime.strptime(text, "%H:%M")
        return dt.hour * 60 + dt.minute
    except ValueError:
        return None


def _minutes_to_hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _normalize_task_name(name: str) -> str:
    text = str(name or "").strip()
    return text if text.startswith("\\") else f"\\{text}"


def query_scheduled_tasks() -> list[dict[str, str]]:
    proc = subprocess.run(
        ["schtasks", "/Query", "/FO", "CSV", "/V"],
        check=False,
        capture_output=True,
        text=True,
        timeout=45,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip())
    return list(csv.DictReader(StringIO(proc.stdout)))


def _task_times(rows: list[dict[str, str]]) -> dict[str, set[str]]:
    times: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        name = _normalize_task_name(row.get("TaskName", ""))
        if name not in EXPECTED_TASKS:
            continue
        minutes = _parse_time_to_minutes(row.get("Start Time", ""))
        if minutes is not None:
            times[name].add(_minutes_to_hhmm(minutes))
    return times


def _task_statuses(rows: list[dict[str, str]]) -> dict[str, set[str]]:
    statuses: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        name = _normalize_task_name(row.get("TaskName", ""))
        if name in EXPECTED_TASKS:
            statuses[name].add(str(row.get("Status", "")).strip())
    return statuses


def build_report(rows: list[dict[str, str]] | None = None) -> dict[str, Any]:
    rows = rows if rows is not None else query_scheduled_tasks()
    actual_times = _task_times(rows)
    statuses = _task_statuses(rows)
    issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    task_rows: list[dict[str, Any]] = []

    for task, expected in EXPECTED_TASKS.items():
        actual = actual_times.get(task, set())
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        status_values = sorted(statuses.get(task, set()))
        if not actual:
            issues.append({"task": task, "issue": "missing_task_or_start_times", "expected": sorted(expected)})
        if missing:
            issues.append({"task": task, "issue": "missing_expected_times", "missing": missing, "actual": sorted(actual)})
        if extra:
            warnings.append({"task": task, "issue": "extra_start_times", "extra": extra, "expected": sorted(expected)})
        if status_values and any(status != "Ready" for status in status_values):
            issues.append({"task": task, "issue": "task_not_ready", "statuses": status_values})
        task_rows.append({
            "task": task,
            "expected": sorted(expected),
            "actual": sorted(actual),
            "statuses": status_values,
            "aligned": not missing and bool(actual) and not any(status != "Ready" for status in status_values),
        })

    first_times = {task: min((_parse_time_to_minutes(t) for t in times), default=None) for task, times in actual_times.items()}
    for name, earlier, later in ORDER_CHECKS:
        e = first_times.get(earlier)
        l = first_times.get(later)
        if e is None or l is None:
            issues.append({"check": name, "issue": "missing_order_task", "earlier": earlier, "later": later})
        elif e >= l:
            issues.append({
                "check": name,
                "issue": "order_violation",
                "earlier": earlier,
                "earlier_time": _minutes_to_hhmm(e),
                "later": later,
                "later_time": _minutes_to_hhmm(l),
            })

    return {
        "date": date.today().isoformat(),
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "market_schedule_alignment",
        "mode": "read_only",
        "execution_enabled": False,
        "timezone": "America/Chicago",
        "regular_market_open_ct": REGULAR_MARKET_OPEN_CT,
        "regular_market_close_ct": REGULAR_MARKET_CLOSE_CT,
        "task_count": len(task_rows),
        "aligned_count": sum(1 for row in task_rows if row["aligned"]),
        "issue_count": len(issues),
        "warning_count": len(warnings),
        "passed": not issues,
        "issues": issues,
        "warnings": warnings,
        "tasks": task_rows,
        "notes": [
            "Times are Central Time on Kenny's Windows machine.",
            "This checks regular trading-day timing. Holiday/half-day handling remains a manual watch item unless an exchange calendar is added.",
            "Portfolio monitor uses a repeating 15-minute task and self-skips outside its monitor window, so it is tracked separately by health/logs.",
        ],
    }


def append_log(report: dict[str, Any], path: Path = LOG_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report, separators=(",", ":"), default=str) + "\n")
    return path


def write_report(report: dict[str, Any], path: Path = REPORT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return path


def print_report(report: dict[str, Any]) -> None:
    print("\nMarket Schedule Alignment | read-only")
    print("=" * 80)
    print(
        f"passed={report['passed']} aligned={report['aligned_count']}/{report['task_count']} "
        f"issues={report['issue_count']} warnings={report['warning_count']}"
    )
    for issue in report["issues"][:12]:
        print(f"ERROR {issue}")
    for warning in report["warnings"][:8]:
        print(f"WARN  {warning}")
    print(f"JSON: {REPORT_PATH}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_output")
    parser.add_argument("--fail-on-issues", action="store_true")
    args = parser.parse_args()
    report = build_report()
    append_log(report, args.log_path)
    write_report(report, args.report_path)
    if args.print_output:
        print_report(report)
    return 1 if args.fail_on_issues and not report["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
