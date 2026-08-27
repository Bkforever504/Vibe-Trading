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
import xml.etree.ElementTree as ET
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
CENTRAL_TO_EASTERN_MINUTES = 60
OPTIONS_ENTRY_WINDOWS_ET = (("09:45", "10:30"), ("15:00", "15:45"))

# A task observed in "Running" state is healthy if it started recently. This
# covers the alignment task observing itself mid-run and other tasks observed
# at their own start minute, while still flagging genuinely stuck tasks.
RUNNING_GRACE_MINUTES = 30
RUNNING_GRACE_MINUTES_BY_TASK = {
    # Registered with an eight-hour execution limit and designed to maintain
    # the market-data/event subscription for the session.
    r"\Flip-Bot-Event-Monitor": 8 * 60,
}


def _minute_series(start: str, end: str, step_minutes: int) -> set[str]:
    """Build an inclusive HH:MM schedule without duplicating long trigger lists."""
    start_hour, start_minute = (int(part) for part in start.split(":"))
    end_hour, end_minute = (int(part) for part in end.split(":"))
    current = start_hour * 60 + start_minute
    final = end_hour * 60 + end_minute
    return {
        f"{minute // 60:02d}:{minute % 60:02d}"
        for minute in range(current, final + 1, step_minutes)
    }


EXPECTED_TASKS = {
    # Timing governance before the rest of the day starts.
    r"\VibeTrade\MarketScheduleAlignment": {"08:10", "19:58"},
    # Premarket context before regular cash open.
    r"\VibeTrade\SocialTrendingSymbolsScanner": {"08:20"},
    r"\VibeTrade\IntradayRiskRefresh": {"08:24"},
    r"\VibeTrade\PreOpenSentimentLogger": {"08:25"},
    # Open + early session.
    r"\Flip-Bot-Event-Monitor": {"08:27"},
    r"\Flip-Bot-Entry": {"08:35"},
    r"\VibeTrade\GEXScanner": {"08:35"},
    r"\VibeTrade\IVRScanner": {"08:35"},
    r"\VibeTrade\RVIVRegimeScanner": {"08:37"},
    r"\VibeTrade\HurstRegimeScanner": {"08:38"},
    r"\VibeTrade\OpeningRangeBreadthScanner": {"08:40"},
    # The exploration runner intentionally retries every 20 minutes through
    # 12:20 CT; its own one-trade-per-day and safety gates prevent duplication.
    r"\Flip-Bot-Exploration": _minute_series("08:40", "12:20", 20),
    r"\VibeTrade\TrendParticipationShadowEntry": {"08:47", "14:02"},
    r"\VibeTrade\TrendParticipationShadowMonitor": {"08:50"},
    # Regular-hours execution/watch.
    # Three staggered 15-minute task families provide one monitor run every
    # five minutes without overlapping scheduler instances.
    r"\Flip-Bot-Monitor": _minute_series("08:45", "15:45", 15),
    r"\Flip-Bot-Monitor-5m-A": _minute_series("08:50", "15:35", 15),
    r"\Flip-Bot-Monitor-5m-B": _minute_series("08:55", "15:40", 15),
    r"\VibeTradingOptionsShadowTwin": {"08:45"},
    r"\VibeTradingShadowScanner": {"09:30", "10:30", "11:30", "12:30", "13:30", "14:30"},
    r"\Flip-Bot-Trend-Entry": {
        "09:45", "10:00", "10:15", "10:30", "10:45", "11:00", "11:15", "11:30",
        "11:45", "12:00", "12:15", "12:30", "12:45", "13:00", "13:15", "13:30", "13:45",
    },
    r"\IWM-Bot-Entry": {"08:45", "14:00"},
    r"\IWM-Bot-Monitor": {"08:35"},
    r"\SPY-Theta-Harvester-Entry": {"08:45"},
    r"\SPY-Theta-Harvester-Monitor": {"09:00", "10:00", "11:00", "12:00", "13:00", "14:00"},
    r"\SPY-Iron-Condor-Entry": {"08:45"},
    r"\SPY-Iron-Condor-Observation": {"08:50"},
    r"\SPY-Iron-Condor-Monitor": {"09:00", "12:00", "14:00"},
    r"\Liquidity-Sweep-Scanner": {"08:43", "09:35", "10:40"},
    r"\SPY-0DTE-PM-Entry": {"11:05", "12:05"},
    r"\SPY-0DTE-PM-Monitor": _minute_series("11:15", "14:45", 15),
    r"\SPY-Wheel-Check": {"08:45"},
    r"\VIX-Call-Hedge-Check": {"09:00"},
    r"\Portfolio-Theta-Dashboard": {"09:30"},
    r"\SPY-Weekend-Vol-Entry": {"13:35"},
    r"\SPY-Weekend-Vol-Monitor": {"08:50", "13:05", "14:05"},
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
    r"\VibeTrade\PatternGrader-Scanner-Intraday": {"08:35"},
    r"\VibeTrade\PatternGrader-Aggregator": {"15:05"},
    r"\PatternGrader-OutcomeResolver": {"15:10"},
    r"\CISD-PromotionTracker": {"15:20"},
    r"\PromoteValidatedPatterns": {"15:30"},
    r"\VibeTrade\SignalStackHealthReport": {"15:40"},
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
    r"\VibeTradingNightlyOptionsNBBOEvidence": {"20:15"},
}

EXPECTED_TASK_REPETITIONS = {
    r"\VibeTrade\PatternGrader-Scanner-Intraday": {"interval": "PT5M", "duration": "PT6H30M"},
    r"\VibeTradingOptionsShadowTwin": {"interval": "PT1M", "duration": "PT6H10M"},
    r"\IWM-Bot-Monitor": {"interval": "PT1M", "duration": "PT6H25M"},
    r"\VibeTrade\TrendParticipationShadowMonitor": {"interval": "PT5M", "duration": "PT6H5M"},
}

ORDER_CHECKS = [
    ("preopen_before_open", r"\VibeTrade\PreOpenSentimentLogger", r"\Flip-Bot-Entry"),
    ("production_entry_before_exploration", r"\Flip-Bot-Entry", r"\Flip-Bot-Exploration"),
    ("open_scanners_before_trend", r"\VibeTrade\OpeningRangeBreadthScanner", r"\Flip-Bot-Trend-Entry"),
    ("opening_range_before_trend_shadow", r"\VibeTrade\OpeningRangeBreadthScanner", r"\VibeTrade\TrendParticipationShadowEntry"),
    ("close_context_before_market_force", r"\VibeTrade\SectorRotationRanker", r"\VibeTrade\MarketForceScore"),
    ("pattern_scanner_before_aggregate", r"\VibeTrade\PatternGrader-Scanner-Intraday", r"\VibeTrade\PatternGrader-Aggregator"),
    ("pattern_aggregate_before_outcomes", r"\VibeTrade\PatternGrader-Aggregator", r"\PatternGrader-OutcomeResolver"),
    ("pattern_outcomes_before_health_report", r"\PatternGrader-OutcomeResolver", r"\VibeTrade\SignalStackHealthReport"),
    ("pattern_outcomes_before_cisd_tracker", r"\PatternGrader-OutcomeResolver", r"\CISD-PromotionTracker"),
    ("cisd_tracker_before_promotion", r"\CISD-PromotionTracker", r"\PromoteValidatedPatterns"),
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


def query_task_repetitions() -> dict[str, dict[str, str]]:
    repetitions: dict[str, dict[str, str]] = {}
    namespace = {"task": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    for task in EXPECTED_TASK_REPETITIONS:
        proc = subprocess.run(
            ["schtasks", "/Query", "/TN", task, "/XML"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if proc.returncode != 0:
            continue
        try:
            root = ET.fromstring(proc.stdout)
        except ET.ParseError:
            continue
        repetition = root.find(".//task:CalendarTrigger/task:Repetition", namespace)
        if repetition is None:
            continue
        interval = repetition.findtext("task:Interval", default="", namespaces=namespace)
        duration = repetition.findtext("task:Duration", default="", namespaces=namespace)
        repetitions[task] = {"interval": interval, "duration": duration}
    return repetitions


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


def _parse_last_run_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text or text.upper() == "N/A":
        return None
    for fmt in ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %I:%M %p"):
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        # Task Scheduler reports 11/30/1999 for never-run tasks.
        return parsed if parsed.year >= 2000 else None
    return None


def _task_last_runs(rows: list[dict[str, str]]) -> dict[str, datetime]:
    last_runs: dict[str, datetime] = {}
    for row in rows:
        name = _normalize_task_name(row.get("TaskName", ""))
        if name not in EXPECTED_TASKS:
            continue
        parsed = _parse_last_run_datetime(row.get("Last Run Time", ""))
        if parsed and (name not in last_runs or parsed > last_runs[name]):
            last_runs[name] = parsed
    return last_runs


def _entry_window_coverage_issues(actual_times: dict[str, set[str]]) -> list[dict[str, Any]]:
    """Require an IWM entry trigger inside every configured Eastern window."""
    task = r"\IWM-Bot-Entry"
    actual_ct = sorted(actual_times.get(task, set()))
    actual_et_minutes = {
        minutes + CENTRAL_TO_EASTERN_MINUTES
        for value in actual_ct
        if (minutes := _parse_time_to_minutes(value)) is not None
    }
    issues: list[dict[str, Any]] = []
    for start_text, end_text in OPTIONS_ENTRY_WINDOWS_ET:
        start = _parse_time_to_minutes(start_text)
        end = _parse_time_to_minutes(end_text)
        if start is None or end is None:
            continue
        if not any(start <= value <= end for value in actual_et_minutes):
            issues.append({
                "task": task,
                "issue": "entry_window_uncovered",
                "window_et": f"{start_text}-{end_text}",
                "actual_ct": actual_ct,
            })
    return issues


def build_report(
    rows: list[dict[str, str]] | None = None,
    now: datetime | None = None,
    task_repetitions: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    live_query = rows is None
    rows = rows if rows is not None else query_scheduled_tasks()
    task_repetitions = (
        task_repetitions
        if task_repetitions is not None
        else query_task_repetitions() if live_query
        else EXPECTED_TASK_REPETITIONS
    )
    now = now or datetime.now()
    actual_times = _task_times(rows)
    statuses = _task_statuses(rows)
    last_runs = _task_last_runs(rows)
    issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    task_rows: list[dict[str, Any]] = []

    for task, expected in EXPECTED_TASKS.items():
        actual = actual_times.get(task, set())
        expected_repetition = EXPECTED_TASK_REPETITIONS.get(task)
        actual_repetition = task_repetitions.get(task)
        repetition_ok = expected_repetition is None or actual_repetition == expected_repetition
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        status_values = sorted(statuses.get(task, set()))
        if not actual:
            issues.append({"task": task, "issue": "missing_task_or_start_times", "expected": sorted(expected)})
        if missing:
            issues.append({"task": task, "issue": "missing_expected_times", "missing": missing, "actual": sorted(actual)})
        if extra:
            warnings.append({"task": task, "issue": "extra_start_times", "extra": extra, "expected": sorted(expected)})
        if expected_repetition is not None and actual_repetition is None:
            issues.append({
                "task": task,
                "issue": "missing_expected_repetition",
                "expected": expected_repetition,
            })
        elif expected_repetition is not None and not repetition_ok:
            issues.append({
                "task": task,
                "issue": "repetition_mismatch",
                "expected": expected_repetition,
                "actual": actual_repetition,
            })
        status_ok = True
        bad_statuses = [status for status in status_values if status not in {"Ready", "Running"}]
        if bad_statuses:
            status_ok = False
            issues.append({"task": task, "issue": "task_not_ready", "statuses": status_values})
        elif "Running" in status_values:
            last_run = last_runs.get(task)
            elapsed_minutes = (now - last_run).total_seconds() / 60 if last_run else None
            running_grace_minutes = RUNNING_GRACE_MINUTES_BY_TASK.get(
                task, RUNNING_GRACE_MINUTES
            )
            if elapsed_minutes is not None and elapsed_minutes > running_grace_minutes:
                status_ok = False
                issues.append({
                    "task": task,
                    "issue": "task_running_too_long",
                    "elapsed_minutes": round(elapsed_minutes, 1),
                    "grace_minutes": running_grace_minutes,
                    "last_run_time": last_run.isoformat(timespec="seconds"),
                })
            elif elapsed_minutes is None:
                warnings.append({
                    "task": task,
                    "issue": "task_running_unknown_duration",
                    "statuses": status_values,
                })
        task_rows.append({
            "task": task,
            "expected": sorted(expected),
            "actual": sorted(actual),
            "expected_repetition": expected_repetition,
            "actual_repetition": actual_repetition,
            "statuses": status_values,
            "aligned": not missing and bool(actual) and status_ok and repetition_ok,
        })

    issues.extend(_entry_window_coverage_issues(actual_times))

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
            "IWM entry triggers must cover both configured Eastern fill-quality windows.",
            "Options shadow and paper position monitors must retain their governed one-minute repetition intervals.",
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
