"""Score creator watchlist tickers against next-day option runner evidence.

Read-only. This turns screenshots/manual creator watchlist notes into a
measurable discovery lane for the small-account bot without routing social
claims into orders.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
OBSERVATIONS_PATH = VIBE_HOME / "creator-watchlist-observations.json"
SOCIAL_OBSERVATIONS_PATH = VIBE_HOME / "social-arb-observations.json"
REPORT_PATH = VIBE_HOME / "reports" / "creator-watchlist-runner-scanner.json"
LOG_PATH = ROOT / "data" / "creator_watchlist_runner_log.jsonl"
SHADOW_PATH = VIBE_HOME / "reports" / "flip-shadow-pnl-evaluator.json"
ASYMMETRY_PATH = VIBE_HOME / "reports" / "cheap-asymmetry-scanner.json"

CASHTAG_RE = re.compile(r"(?<![A-Z0-9])\$([A-Z][A-Z0-9]{0,5})(?:\b|$)")
IGNORED = {"SPX.X", "VIX.X"}
RUNNER_RETURN_PCT = 50.0
STRONG_RUNNER_RETURN_PCT = 100.0


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


def _date_part(value: Any) -> str:
    raw = str(value or "")
    return raw[:10] if len(raw) >= 10 else ""


def _extract_symbols(row: dict[str, Any]) -> list[str]:
    symbols: list[str] = []
    raw_symbols = row.get("symbols")
    if isinstance(raw_symbols, list):
        for item in raw_symbols:
            symbol = str(item or "").upper().lstrip("$")
            if symbol and symbol not in symbols:
                symbols.append(symbol)
    for key in ("keyword", "ticker", "symbol", "caption", "title"):
        text = str(row.get(key) or "").upper()
        for match in CASHTAG_RE.finditer(text):
            symbol = match.group(1).upper()
            if symbol and symbol not in symbols and symbol not in IGNORED:
                symbols.append(symbol)
    return symbols


def _load_creator_observations(path: Path, social_path: Path, day: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source_path in (path, social_path):
        payload = _read_json(source_path, [])
        if not isinstance(payload, list):
            continue
        for raw in payload:
            if not isinstance(raw, dict):
                continue
            symbols = _extract_symbols(raw)
            if not symbols:
                continue
            observed_day = _date_part(raw.get("observed_at") or raw.get("date"))
            if observed_day and observed_day > day:
                continue
            source = str(raw.get("source") or "")
            caption = str(raw.get("caption") or raw.get("title") or "")
            if source.startswith("x_manual") or "watchlist" in caption.lower() or "called" in caption.lower():
                rows.append({**raw, "symbols": symbols, "observed_day": observed_day})
    return rows


def _shadow_by_symbol(path: Path, day: str) -> dict[str, dict[str, Any]]:
    payload = _read_json(path, {})
    if not isinstance(payload, dict) or str(payload.get("date") or "")[:10] != day:
        return {}
    by_symbol = payload.get("by_symbol") if isinstance(payload.get("by_symbol"), dict) else {}
    top_trades = payload.get("top_trades") if isinstance(payload.get("top_trades"), list) else []
    merged: dict[str, dict[str, Any]] = {
        str(symbol).upper(): stats.copy()
        for symbol, stats in by_symbol.items()
        if isinstance(stats, dict)
    }
    for trade in top_trades:
        if not isinstance(trade, dict):
            continue
        symbol = str(trade.get("symbol") or "").upper()
        if not symbol:
            continue
        item = merged.setdefault(symbol, {})
        if _safe_float(trade.get("return_pct")) > _safe_float(item.get("best_return_pct")):
            item["best_return_pct"] = trade.get("return_pct")
            item["best_option_symbol"] = trade.get("option_symbol")
            item["best_right"] = trade.get("right")
            item["best_entry_price"] = trade.get("entry_price")
            item["best_simulated_return_pct"] = trade.get("simulated_exit_return_pct")
    return merged


def _cheap_asymmetry_symbols(path: Path, day: str) -> dict[str, dict[str, Any]]:
    payload = _read_json(path, {})
    if not isinstance(payload, dict) or str(payload.get("date") or "")[:10] != day:
        return {}
    candidates = payload.get("top_candidates") if isinstance(payload.get("top_candidates"), list) else []
    output: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        symbol = str(candidate.get("symbol") or "").upper()
        if symbol:
            output[symbol] = candidate
    return output


def build_report(
    *,
    day: str | None = None,
    observations_path: Path = OBSERVATIONS_PATH,
    social_observations_path: Path = SOCIAL_OBSERVATIONS_PATH,
    shadow_path: Path = SHADOW_PATH,
    asymmetry_path: Path = ASYMMETRY_PATH,
) -> dict[str, Any]:
    day = day or date.today().isoformat()
    observations = _load_creator_observations(observations_path, social_observations_path, day)
    shadow = _shadow_by_symbol(shadow_path, day)
    cheap = _cheap_asymmetry_symbols(asymmetry_path, day)

    grouped: dict[str, dict[str, Any]] = {}
    for obs in observations:
        for symbol in obs["symbols"]:
            item = grouped.setdefault(symbol, {
                "symbol": symbol,
                "sources": set(),
                "creators": set(),
                "captions": [],
                "first_observed_at": obs.get("observed_at") or obs.get("date") or "",
                "observed_days": set(),
            })
            item["sources"].add(str(obs.get("source") or "manual"))
            creator = str(obs.get("creator") or obs.get("account") or obs.get("platform") or "")
            if creator:
                item["creators"].add(creator)
            caption = str(obs.get("caption") or obs.get("title") or "")
            if caption and len(item["captions"]) < 3:
                item["captions"].append(caption[:300])
            if obs.get("observed_day"):
                item["observed_days"].add(str(obs["observed_day"]))

    results: list[dict[str, Any]] = []
    for symbol, item in grouped.items():
        stats = shadow.get(symbol, {})
        cheap_stats = cheap.get(symbol, {})
        best_return = _safe_float(stats.get("best_return_pct"))
        cheap_detected = bool(cheap_stats)
        runner_detected = best_return >= RUNNER_RETURN_PCT
        observed_days = sorted(item["observed_days"])
        called_before_or_same_day = any(obs_day <= day for obs_day in observed_days) if observed_days else False
        if best_return >= STRONG_RUNNER_RETURN_PCT:
            verdict = "strong_runner_confirmed"
        elif runner_detected:
            verdict = "runner_confirmed"
        elif symbol in shadow:
            verdict = "shadow_seen_no_runner"
        else:
            verdict = "needs_shadow_evidence"
        results.append({
            "symbol": symbol,
            "runner_detected": runner_detected,
            "cheap_asymmetry_detected": cheap_detected,
            "called_before_or_same_day": called_before_or_same_day,
            "best_return_pct": round(best_return, 2),
            "shadow_sample_count": int(_safe_float(stats.get("sample_count"))),
            "shadow_completed_count": int(_safe_float(stats.get("completed_count"))),
            "shadow_win_rate": round(_safe_float(stats.get("win_rate")), 3),
            "total_hypothetical_pnl": round(_safe_float(stats.get("total_hypothetical_pnl")), 2),
            "best_option_symbol": stats.get("best_option_symbol") or cheap_stats.get("option_symbol"),
            "cost_at_open": cheap_stats.get("cost_at_open"),
            "sources": sorted(item["sources"]),
            "creators": sorted(item["creators"]),
            "first_observed_at": item["first_observed_at"],
            "observed_days": observed_days,
            "captions": item["captions"],
            "verdict": verdict,
            "execution_enabled": False,
        })

    results.sort(
        key=lambda row: (
            bool(row["runner_detected"]),
            bool(row["cheap_asymmetry_detected"]),
            _safe_float(row["best_return_pct"]),
            row["symbol"],
        ),
        reverse=True,
    )
    runner_count = sum(1 for row in results if row["runner_detected"])
    cheap_count = sum(1 for row in results if row["cheap_asymmetry_detected"])
    return {
        "provider": "creator_watchlist_runner_scanner",
        "mode": "read_only",
        "execution_enabled": False,
        "date": day,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "summary": {
            "observation_count": len(observations),
            "symbol_count": len(results),
            "runner_count": runner_count,
            "cheap_asymmetry_count": cheap_count,
            "promotion_ready_count": 0,
        },
        "watchlist_results": results,
        "promotion_note": "Read-only discovery lane. No creator/watchlist ticker can route to orders without 30 trading days, 10 completed shadow samples, liquidity proof, and explicit approval.",
        "warnings": [
            "No broker calls. No orders placed.",
            "Creator screenshots are discovery prompts, not evidence by themselves.",
            "Hindsight P/L claims must be verified by independent shadow logs before any promotion.",
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
    print("\nCreator Watchlist Runner Scanner | read-only")
    print("=" * 76)
    print(
        f"date={report['date']} symbols={summary['symbol_count']} "
        f"runners={summary['runner_count']} cheap={summary['cheap_asymmetry_count']} "
        f"promotion_ready={summary['promotion_ready_count']}"
    )
    for row in report["watchlist_results"][:12]:
        print(
            f"{row['symbol']:<6} ret={row['best_return_pct']:>7.2f}% "
            f"runner={row['runner_detected']} cheap={row['cheap_asymmetry_detected']} "
            f"verdict={row['verdict']}"
        )
    print("No orders placed. No execution settings changed.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Score creator watchlist tickers against shadow option runners.")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--observations", type=Path, default=OBSERVATIONS_PATH)
    parser.add_argument("--social-observations", type=Path, default=SOCIAL_OBSERVATIONS_PATH)
    parser.add_argument("--shadow-path", type=Path, default=SHADOW_PATH)
    parser.add_argument("--asymmetry-path", type=Path, default=ASYMMETRY_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()

    report = build_report(
        day=args.date,
        observations_path=args.observations,
        social_observations_path=args.social_observations,
        shadow_path=args.shadow_path,
        asymmetry_path=args.asymmetry_path,
    )
    write_report(report, args.report_path)
    append_log(report, args.log_path)
    if args.do_print:
        print_report(report)
    else:
        print(f"Creator watchlist runner report written to {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
