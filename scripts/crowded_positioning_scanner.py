"""Read-only crowded-positioning scanner.

Aggregates liquidation/positioning context into a simple posture map for the
bot stack. It does not fetch broker data, place orders, or modify strategy
settings.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_DIR = VIBE_HOME / "reports"
MOONDEV_PATH = REPORT_DIR / "moondev-liquidation-context.json"
PREDICTION_PATH = REPORT_DIR / "prediction-market-microstructure.json"
WEEKLY_HOT_PATH = REPORT_DIR / "weekly-hot-instruments.json"
REPORT_PATH = REPORT_DIR / "crowded-positioning-scanner.json"
LOG_PATH = ROOT / "data" / "crowded_positioning_log.jsonl"


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return fallback


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _same_day(payload: dict[str, Any], day: str) -> bool:
    return str(payload.get("date") or "")[:10] == day


def _score_crowding(moondev: dict[str, Any], prediction: dict[str, Any]) -> tuple[str, int, list[str]]:
    score = 0
    long_points = 0
    short_points = 0
    reasons: list[str] = []

    pressure = str(moondev.get("liquidation_pressure") or "")
    if pressure == "long_squeeze_pressure":
        score += 4
        long_points += 4
        reasons.append("liquidation pressure indicates crowded longs being squeezed")
    elif pressure == "short_squeeze_pressure":
        score += 4
        short_points += 4
        reasons.append("liquidation pressure indicates crowded shorts being squeezed")
    elif pressure == "high_two_sided_liquidation":
        score += 3
        reasons.append("high two-sided liquidation pressure")

    liqs = moondev.get("liquidations") if isinstance(moondev.get("liquidations"), dict) else {}
    total_liq = _safe_float(liqs.get("total_volume_usd"))
    if total_liq >= 100_000_000:
        score += 2
        reasons.append("liquidation volume above $100M")

    hlp = moondev.get("hlp_sentiment") if isinstance(moondev.get("hlp_sentiment"), dict) else {}
    hlp_bias = str(hlp.get("bias") or "")
    if hlp_bias == "retail_long_squeeze_risk":
        score += 3
        long_points += 3
        reasons.append("HLP sentiment flags retail long squeeze risk")
    elif hlp_bias == "retail_short_squeeze_risk":
        score += 3
        short_points += 3
        reasons.append("HLP sentiment flags retail short squeeze risk")

    positions = moondev.get("position_snapshots") if isinstance(moondev.get("position_snapshots"), dict) else {}
    if _safe_float(positions.get("total_snapshots")) >= 100:
        score += 1
        reasons.append("position snapshot sample is meaningful")
    if 0 < _safe_float(positions.get("avg_distance_pct")) <= 5:
        score += 1
        reasons.append("average liquidation distance is close")

    for row in prediction.get("top_candidates") or []:
        if not isinstance(row, dict):
            continue
        if _safe_float(row.get("microstructure_score")) < 5:
            continue
        hint = str(row.get("directional_hint") or "")
        score += 1
        if hint in {"no_flow", "down_flow"}:
            long_points += 1
            reasons.append("prediction flow leans bearish/down")
        elif hint in {"yes_flow", "up_flow"}:
            short_points += 1
            reasons.append("prediction flow leans bullish/up")

    if long_points > short_points:
        side = "long"
    elif short_points > long_points:
        side = "short"
    elif score >= 5:
        side = "two_sided"
    else:
        side = "none"
    return side, min(score, 10), reasons


def _flip_context(crowded_side: str, score: int) -> dict[str, Any]:
    if crowded_side == "long" and score >= 6:
        return {
            "posture": "cautious",
            "call_bias": "avoid_chasing_calls",
            "put_bias": "only_with_clean_trend_confirmation",
            "stand_aside_rule": "stand aside when Flip Bot signal conflicts with bearish liquidation pressure",
        }
    if crowded_side == "short" and score >= 6:
        return {
            "posture": "cautious",
            "call_bias": "watch_for_squeeze_but_require_confirmation",
            "put_bias": "avoid_chasing_puts",
            "stand_aside_rule": "stand aside when short squeeze pressure conflicts with bearish entries",
        }
    if crowded_side == "two_sided":
        return {
            "posture": "cautious",
            "call_bias": "neutral",
            "put_bias": "neutral",
            "stand_aside_rule": "avoid low-confidence entries during two-sided liquidation stress",
        }
    return {
        "posture": "normal",
        "call_bias": "neutral",
        "put_bias": "neutral",
        "stand_aside_rule": "no positioning override",
    }


def _crypto_proxy_watchlist(weekly: dict[str, Any]) -> list[str]:
    rows = weekly.get("hot_instruments") if isinstance(weekly.get("hot_instruments"), list) else []
    symbols: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        bucket = str(row.get("bucket") or "")
        symbol = str(row.get("symbol") or "").upper()
        if bucket == "crypto_equity_proxy" and _safe_float(row.get("hot_score")) >= 5 and symbol not in symbols:
            symbols.append(symbol)
    return symbols[:8]


def build_report(
    *,
    day: str | None = None,
    moondev_path: Path = MOONDEV_PATH,
    prediction_path: Path = PREDICTION_PATH,
    weekly_hot_path: Path = WEEKLY_HOT_PATH,
) -> dict[str, Any]:
    day = day or date.today().isoformat()
    moondev = _read_json(moondev_path, {})
    prediction = _read_json(prediction_path, {})
    weekly = _read_json(weekly_hot_path, {})
    if not isinstance(moondev, dict) or not _same_day(moondev, day):
        moondev = {}
    if not isinstance(prediction, dict) or not _same_day(prediction, day):
        prediction = {}
    if not isinstance(weekly, dict) or not _same_day(weekly, day):
        weekly = {}

    crowded_side, score, reasons = _score_crowding(moondev, prediction)
    return {
        "provider": "crowded_positioning_scanner",
        "mode": "read_only",
        "execution_enabled": False,
        "promotion_ready": False,
        "date": day,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "summary": {
            "crowded_side": crowded_side,
            "crowding_score": score,
            "source_status": moondev.get("status", "missing"),
            "liquidation_pressure": moondev.get("liquidation_pressure", "unknown"),
            "reason_count": len(reasons),
        },
        "reasons": reasons,
        "flip_bot_context": _flip_context(crowded_side, score),
        "crypto_proxy_watchlist": _crypto_proxy_watchlist(weekly),
        "source_paths": {
            "moondev": str(moondev_path),
            "prediction_microstructure": str(prediction_path),
            "weekly_hot_instruments": str(weekly_hot_path),
        },
        "warnings": [
            "Read-only context. No broker calls, no orders, and no bot settings changed.",
            "Crowded positioning is a caution layer, not an entry signal.",
            "Requires 30 trading days of outcome review before it can become a gate.",
        ],
    }


def write_report(report: dict[str, Any], report_path: Path = REPORT_PATH) -> Path:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report_path


def append_log(report: dict[str, Any], log_path: Path = LOG_PATH) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")


def print_report(report: dict[str, Any]) -> None:
    summary = report["summary"]
    flip = report["flip_bot_context"]
    print("\nCrowded Positioning Scanner | read-only")
    print("=" * 72)
    print(
        f"date={report['date']} side={summary['crowded_side']} "
        f"score={summary['crowding_score']} posture={flip['posture']} "
        f"pressure={summary['liquidation_pressure']}"
    )
    for reason in report["reasons"][:6]:
        print(f"- {reason}")
    if report["crypto_proxy_watchlist"]:
        print("crypto proxies: " + ", ".join(report["crypto_proxy_watchlist"]))
    print("No orders placed. No execution settings changed.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build read-only crowded positioning report.")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--moondev-path", type=Path, default=MOONDEV_PATH)
    parser.add_argument("--prediction-path", type=Path, default=PREDICTION_PATH)
    parser.add_argument("--weekly-hot-path", type=Path, default=WEEKLY_HOT_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()

    report = build_report(
        day=args.date,
        moondev_path=args.moondev_path,
        prediction_path=args.prediction_path,
        weekly_hot_path=args.weekly_hot_path,
    )
    write_report(report, args.report_path)
    append_log(report, args.log_path)
    if args.do_print:
        print_report(report)
    else:
        print(f"Crowded positioning report written to {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
