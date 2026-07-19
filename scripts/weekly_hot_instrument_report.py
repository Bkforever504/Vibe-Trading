"""Rolling weekly hot-instrument report.

Combines social persistence with Flip Bot shadow-candidate outcomes so we can
track the tickers repeatedly showing up on X/StockTwits/Reddit-style chatter
without promoting anything to live trading from a screenshot.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
VIBE_HOME = Path.home() / ".vibe-trading"
SOCIAL_LOG_PATH = ROOT / "data" / "social_trending_symbols_log.jsonl"
SHADOW_EVAL_LOG_PATH = ROOT / "data" / "flip_shadow_pnl_evaluation_log.jsonl"
SOCIAL_ARB_OBSERVATIONS_PATH = VIBE_HOME / "social-arb-observations.json"
DEEP_UNIVERSE_LOG_PATH = ROOT / "data" / "deep_liquid_universe_scan_log.jsonl"
OPTIONS_LIQUIDITY_REPORT_PATH = VIBE_HOME / "reports" / "options-liquidity-feasibility.json"
REPORT_PATH = VIBE_HOME / "reports" / "weekly-hot-instruments.json"
LOG_PATH = ROOT / "data" / "weekly_hot_instrument_log.jsonl"

LIQUID_SHADOW_SYMBOLS = {"SPY", "QQQ", "IWM", "NVDA", "TSLA", "AAPL"}
HIGH_NOISE_BUCKETS = {"meme_high_noise", "social_squeeze_watch", "crypto"}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _cutoff_date(days: int, today: str | None = None) -> str:
    anchor = date.fromisoformat(today) if today else datetime.now(timezone.utc).date()
    return (anchor - timedelta(days=max(days - 1, 0))).isoformat()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _social_rows(path: Path, cutoff: str, today: str) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "symbol": "",
        "dates": set(),
        "slots": set(),
        "best_rank": None,
        "max_trending_score": 0.0,
        "bucket": "",
        "social_action": "",
        "risk_flags": set(),
        "summaries": [],
    })
    for row in _read_jsonl(path):
        row_date = str(row.get("date") or "")[:10]
        if not row_date or row_date < cutoff or row_date > today:
            continue
        slot = _safe_int(row.get("intraday_scan_index"), 0)
        for symbol_row in row.get("symbols") or []:
            if not isinstance(symbol_row, dict):
                continue
            symbol = str(symbol_row.get("symbol") or "").upper()
            if not symbol:
                continue
            item = grouped[symbol]
            item["symbol"] = symbol
            item["dates"].add(row_date)
            item["slots"].add(f"{row_date}:{slot}")
            rank = _safe_int(symbol_row.get("rank"), 999)
            item["best_rank"] = rank if item["best_rank"] is None else min(int(item["best_rank"]), rank)
            item["max_trending_score"] = max(
                float(item["max_trending_score"]),
                _safe_float(symbol_row.get("trending_score")),
            )
            item["bucket"] = item["bucket"] or str(symbol_row.get("bucket") or "")
            item["social_action"] = item["social_action"] or str(symbol_row.get("action") or "")
            for flag in symbol_row.get("noise_flags") or []:
                item["risk_flags"].add(str(flag))
            summary = str(symbol_row.get("summary") or "")
            if summary and len(item["summaries"]) < 2:
                item["summaries"].append(summary[:300])
    return grouped


def _latest_shadow_summary(path: Path, cutoff: str, today: str) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    latest_key: dict[str, tuple[str, str]] = {}
    for row in _read_jsonl(path):
        row_date = str(row.get("date") or "")[:10]
        if not row_date or row_date < cutoff or row_date > today:
            continue
        by_symbol = row.get("by_symbol") if isinstance(row.get("by_symbol"), dict) else {}
        for symbol, stats in by_symbol.items():
            if not isinstance(stats, dict):
                continue
            sym = str(symbol).upper()
            key = (row_date, str(row.get("timestamp") or row.get("generated_at") or ""))
            if key < latest_key.get(sym, ("", "")):
                continue
            completed = _safe_int(stats.get("completed_count"))
            winner_count = _safe_int(stats.get("winner_count"))
            if winner_count == 0 and completed and stats.get("win_rate") is not None:
                winner_count = round(_safe_float(stats.get("win_rate")) * completed)
            latest_key[sym] = key
            merged[sym] = {
                "shadow_sample_count": _safe_int(stats.get("sample_count")),
                "shadow_completed_count": completed,
                "shadow_trading_day_count": _safe_int(stats.get("trading_day_count")),
                "shadow_winner_count": winner_count,
                "best_shadow_return_pct": _safe_float(stats.get("best_return_pct")),
                "total_hypothetical_pnl": _safe_float(stats.get("total_hypothetical_pnl")),
                "shadow_expectancy_return_pct": _safe_float(stats.get("expectancy_return_pct")),
                "shadow_avg_win_return_pct": _safe_float(stats.get("avg_win_return_pct")),
                "shadow_avg_loss_return_pct": _safe_float(stats.get("avg_loss_return_pct")),
                "shadow_payoff_ratio": stats.get("payoff_ratio"),
                "shadow_promotion_eligible": bool(stats.get("promotion_eligible")),
            }
    for stats in merged.values():
        completed = _safe_int(stats.get("shadow_completed_count"))
        stats["shadow_win_rate"] = round(_safe_int(stats.get("shadow_winner_count")) / completed, 3) if completed else 0.0
        stats["total_hypothetical_pnl"] = round(_safe_float(stats.get("total_hypothetical_pnl")), 2)
        stats["best_shadow_return_pct"] = round(_safe_float(stats.get("best_shadow_return_pct")), 2)
    return merged


def _social_arb_summary(path: Path, cutoff: str, today: str) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return {}
    observations = payload if isinstance(payload, list) else []
    summary: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "symbol": "",
        "source_count": 0,
        "sources": set(),
        "observation_count": 0,
        "theme": "",
        "examples": [],
    })
    try:
        from strategies.social_arbitrage_watchlist import score_social_arbitrage
    except Exception:
        score_social_arbitrage = None

    filtered = []
    for row in observations:
        if not isinstance(row, dict):
            continue
        observed_at = str(row.get("observed_at") or row.get("date") or "")[:10]
        if observed_at and (observed_at < cutoff or observed_at > today):
            continue
        filtered.append(row)

    if score_social_arbitrage:
        for idea in score_social_arbitrage(filtered):
            symbol = str(idea.get("ticker") or "").upper()
            if not symbol:
                continue
            item = summary[symbol]
            item["symbol"] = symbol
            item["source_count"] = _safe_int(idea.get("source_count"))
            item["sources"].update(str(source) for source in idea.get("sources") or [])
            item["observation_count"] = len(idea.get("examples") or [])
            item["theme"] = str(idea.get("theme") or "")
            item["examples"] = idea.get("examples") or []
    return summary


def _deep_universe_summary(path: Path, cutoff: str, today: str) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(path):
        row_date = str(row.get("date") or "")[:10]
        if not row_date or row_date < cutoff or row_date > today:
            continue
        for source_key in ("top_candidates", "watch_context"):
            for candidate in row.get(source_key) or []:
                if not isinstance(candidate, dict):
                    continue
                symbol = str(candidate.get("symbol") or "").upper()
                if not symbol:
                    continue
                prior = summary.get(symbol, {})
                if _safe_float(candidate.get("deep_score")) < _safe_float(prior.get("deep_score")):
                    continue
                summary[symbol] = {
                    "symbol": symbol,
                    "deep_score": _safe_float(candidate.get("deep_score")),
                    "deep_recommendation": str(candidate.get("recommendation") or ""),
                    "deep_relative_volume": _safe_float(candidate.get("relative_volume")),
                    "deep_one_day_pct": _safe_float(candidate.get("one_day_pct")),
                    "deep_twenty_day_pct": _safe_float(candidate.get("twenty_day_pct")),
                    "deep_reasons": candidate.get("reasons") if isinstance(candidate.get("reasons"), list) else [],
                }
    return summary


def _options_liquidity_summary(path: Path | None, cutoff: str, today: str) -> dict[str, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return {}
    report_date = str(payload.get("date") or "")[:10]
    if not report_date or report_date < cutoff or report_date > today:
        return {}

    summary: dict[str, dict[str, Any]] = {}
    for row in payload.get("results") or []:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").upper()
        if not symbol:
            continue
        criteria = row.get("criteria") if isinstance(row.get("criteria"), dict) else {}
        status_ok = str(row.get("status") or "") == "ok"
        has_expiry = bool(row.get("has_0dte") or row.get("has_weekly"))
        spread_ok = bool(row.get("spread_ok") or criteria.get("spread_ok"))
        volume_ok = bool(row.get("volume_ok") or criteria.get("volume_ok"))
        price_ok = bool(row.get("price_ok") or criteria.get("price_ok"))
        execution_quality_ok = status_ok and has_expiry and spread_ok and volume_ok and price_ok
        summary[symbol] = {
            "symbol": symbol,
            "checked": True,
            "status": str(row.get("status") or "unknown"),
            "verdict": str(row.get("verdict") or "unknown"),
            "score": _safe_float(row.get("score")),
            "has_0dte": bool(row.get("has_0dte")),
            "has_weekly": bool(row.get("has_weekly")),
            "spread_ok": spread_ok,
            "volume_ok": volume_ok,
            "price_ok": price_ok,
            "execution_quality_ok": execution_quality_ok,
            "atm_spread_pct": row.get("atm_spread_pct"),
            "atm_volume_min": _safe_int(row.get("atm_volume_min")),
            "atm_oi_min": _safe_int(row.get("atm_oi_min")),
            "atm_price_per_contract": row.get("atm_price_per_contract"),
            "chain_expiry_used": row.get("chain_expiry_used"),
        }
    return summary


def _score_candidate(item: dict[str, Any]) -> tuple[float, str, list[str]]:
    score = 0.0
    reasons: list[str] = []
    symbol = str(item.get("symbol") or "")
    bucket = str(item.get("bucket") or "")
    risk_flags = list(item.get("risk_flags") or [])

    social_days = _safe_int(item.get("social_day_count"))
    social_slots = _safe_int(item.get("social_slot_count"))
    if social_days:
        score += min(3.0, social_days * 1.0)
        reasons.append("social ticker appeared across the rolling window")
    if social_slots >= 2:
        score += min(2.0, social_slots * 0.35)
        reasons.append("intraday social persistence repeated")
    if _safe_float(item.get("max_trending_score")) >= 7:
        score += 0.75
        reasons.append("high social trending score")
    if _safe_int(item.get("social_arb_observation_count")):
        score += min(2.0, _safe_int(item.get("social_arb_observation_count")) * 0.75)
        reasons.append("manual social observation captured")
    deep_score = _safe_float(item.get("deep_universe_score"))
    if deep_score >= 6:
        score += min(2.0, deep_score / 5.0)
        reasons.append("deep liquid universe scan flagged the symbol")

    if bool(item.get("options_execution_quality_ok")):
        score += 1.5
        reasons.append("current option chain has executable spread, volume, and price")
    elif bool(item.get("options_liquidity_checked")):
        score -= 3.0
        reasons.append("current option chain failed direct Flip Bot execution quality")

    completed = _safe_int(item.get("shadow_completed_count"))
    win_rate = _safe_float(item.get("shadow_win_rate"))
    expectancy = _safe_float(item.get("shadow_expectancy_return_pct"))
    best_return = _safe_float(item.get("best_shadow_return_pct"))
    if completed:
        score += min(3.0, completed * 0.45)
        reasons.append("options/liquidity shadow evidence is building")
    if expectancy > 0 and completed >= 3:
        score += min(2.0, expectancy / 20.0)
        reasons.append("shadow expectancy is positive")
    elif completed >= 3 and expectancy <= 0:
        score -= 3.0
        reasons.append("shadow expectancy is non-positive")
    if win_rate >= 0.6 and completed >= 3 and expectancy > 0:
        score += 1.5
        reasons.append("shadow candidates are winning so far")
    if best_return >= 75:
        score += 1.0
        reasons.append("at least one candidate hit the 75% Flip Bot style target")

    if bucket in HIGH_NOISE_BUCKETS or risk_flags:
        score -= 2.0
    if symbol in LIQUID_SHADOW_SYMBOLS:
        score += 0.75

    if bucket in HIGH_NOISE_BUCKETS or risk_flags:
        action = "research_only"
    elif bool(item.get("shadow_promotion_eligible")) and expectancy > 0:
        action = "promotion_review"
    elif completed >= 3 and win_rate >= 0.6 and expectancy > 0 and score >= 5:
        action = "priority_shadow_review"
    elif social_days >= 2 or completed or deep_score >= 6:
        action = "watch_context"
    else:
        action = "observe"
    return round(max(0.0, score), 2), action, reasons


def build_report(
    *,
    social_log_path: Path = SOCIAL_LOG_PATH,
    shadow_eval_log_path: Path = SHADOW_EVAL_LOG_PATH,
    social_arb_observations_path: Path = SOCIAL_ARB_OBSERVATIONS_PATH,
    deep_universe_log_path: Path = DEEP_UNIVERSE_LOG_PATH,
    options_liquidity_report_path: Path | None = None,
    days: int = 7,
    today: str | None = None,
) -> dict[str, Any]:
    today = today or date.today().isoformat()
    cutoff = _cutoff_date(days, today)
    social = _social_rows(social_log_path, cutoff, today)
    shadow = _latest_shadow_summary(shadow_eval_log_path, cutoff, today)
    social_arb = _social_arb_summary(social_arb_observations_path, cutoff, today)
    deep = _deep_universe_summary(deep_universe_log_path, cutoff, today)
    options_liquidity = _options_liquidity_summary(options_liquidity_report_path, cutoff, today)
    symbols = sorted(set(social) | set(shadow) | set(social_arb) | set(deep) | set(options_liquidity))

    instruments: list[dict[str, Any]] = []
    for symbol in symbols:
        social_item = social.get(symbol, {})
        shadow_item = shadow.get(symbol, {})
        social_arb_item = social_arb.get(symbol, {})
        deep_item = deep.get(symbol, {})
        liquidity_item = options_liquidity.get(symbol, {})
        social_arb_theme = str(social_arb_item.get("theme") or "")
        liquidity_risk_flags: set[str] = set()
        if liquidity_item and not liquidity_item.get("execution_quality_ok"):
            if not liquidity_item.get("spread_ok"):
                liquidity_risk_flags.add("options_spread_above_threshold")
            if not liquidity_item.get("volume_ok"):
                liquidity_risk_flags.add("options_volume_below_threshold")
            if not liquidity_item.get("price_ok"):
                liquidity_risk_flags.add("direct_option_contract_above_flip_budget")
            if liquidity_item.get("status") != "ok":
                liquidity_risk_flags.add("options_liquidity_unavailable")
        item: dict[str, Any] = {
            "symbol": symbol,
            "bucket": social_item.get("bucket")
            or ("social_squeeze_watch" if "squeeze" in social_arb_theme else "")
            or ("liquid_shadow_candidate" if symbol in LIQUID_SHADOW_SYMBOLS else "unknown"),
            "social_day_count": len(social_item.get("dates") or []),
            "social_slot_count": len(social_item.get("slots") or []),
            "best_social_rank": social_item.get("best_rank"),
            "max_trending_score": round(_safe_float(social_item.get("max_trending_score")), 4),
            "social_action": social_item.get("social_action") or "",
            "risk_flags": sorted(
                set(social_item.get("risk_flags") or [])
                | ({"social squeeze watch; context only until options/liquidity/outcome validate"} if "squeeze" in social_arb_theme else set())
                | liquidity_risk_flags
            ),
            "summaries": social_item.get("summaries") or [],
            "social_arb_source_count": _safe_int(social_arb_item.get("source_count")),
            "social_arb_observation_count": _safe_int(social_arb_item.get("observation_count")),
            "social_arb_sources": sorted(social_arb_item.get("sources") or []),
            "social_arb_theme": social_arb_theme,
            "shadow_sample_count": _safe_int(shadow_item.get("shadow_sample_count")),
            "shadow_completed_count": _safe_int(shadow_item.get("shadow_completed_count")),
            "shadow_trading_day_count": _safe_int(shadow_item.get("shadow_trading_day_count")),
            "shadow_win_rate": _safe_float(shadow_item.get("shadow_win_rate")),
            "shadow_expectancy_return_pct": _safe_float(shadow_item.get("shadow_expectancy_return_pct")),
            "shadow_avg_win_return_pct": _safe_float(shadow_item.get("shadow_avg_win_return_pct")),
            "shadow_avg_loss_return_pct": _safe_float(shadow_item.get("shadow_avg_loss_return_pct")),
            "shadow_payoff_ratio": shadow_item.get("shadow_payoff_ratio"),
            "shadow_promotion_eligible": bool(shadow_item.get("shadow_promotion_eligible")),
            "best_shadow_return_pct": _safe_float(shadow_item.get("best_shadow_return_pct")),
            "total_hypothetical_pnl": _safe_float(shadow_item.get("total_hypothetical_pnl")),
            "deep_universe_score": _safe_float(deep_item.get("deep_score")),
            "deep_universe_recommendation": deep_item.get("deep_recommendation", ""),
            "deep_relative_volume": _safe_float(deep_item.get("deep_relative_volume")),
            "deep_one_day_pct": _safe_float(deep_item.get("deep_one_day_pct")),
            "deep_twenty_day_pct": _safe_float(deep_item.get("deep_twenty_day_pct")),
            "deep_reasons": deep_item.get("deep_reasons", []),
            "options_liquidity_checked": bool(liquidity_item.get("checked")),
            "options_liquidity_status": liquidity_item.get("status"),
            "options_liquidity_verdict": liquidity_item.get("verdict"),
            "options_liquidity_score": _safe_float(liquidity_item.get("score")),
            "options_execution_quality_ok": bool(liquidity_item.get("execution_quality_ok")),
            "options_has_0dte": bool(liquidity_item.get("has_0dte")),
            "options_has_weekly": bool(liquidity_item.get("has_weekly")),
            "options_spread_ok": bool(liquidity_item.get("spread_ok")),
            "options_volume_ok": bool(liquidity_item.get("volume_ok")),
            "options_price_ok": bool(liquidity_item.get("price_ok")),
            "options_atm_spread_pct": liquidity_item.get("atm_spread_pct"),
            "options_atm_volume_min": _safe_int(liquidity_item.get("atm_volume_min")),
            "options_atm_oi_min": _safe_int(liquidity_item.get("atm_oi_min")),
            "options_atm_price_per_contract": liquidity_item.get("atm_price_per_contract"),
        }
        score, action, reasons = _score_candidate(item)
        item["hot_score"] = score
        item["action"] = action
        item["reasons"] = reasons
        instruments.append(item)

    instruments.sort(
        key=lambda row: (
            float(row.get("hot_score") or 0.0),
            _safe_int(row.get("shadow_completed_count")),
            _safe_int(row.get("social_slot_count")),
            _safe_float(row.get("best_shadow_return_pct")),
        ),
        reverse=True,
    )
    manual_social = [
        item for item in instruments
        if _safe_int(item.get("social_arb_observation_count")) > 0
    ]
    verifier_instruments = [
        item for item in instruments
        if str(item.get("symbol") or "") in LIQUID_SHADOW_SYMBOLS
        or item.get("action") in {"priority_shadow_review", "promotion_review"}
    ]
    return {
        "provider": "weekly_hot_instrument_report",
        "mode": "read_only",
        "execution_enabled": False,
        "date": today,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "lookback_days": days,
        "cutoff_date": cutoff,
        "source_logs": {
            "social": str(social_log_path),
            "flip_shadow_pnl": str(shadow_eval_log_path),
            "social_arbitrage_observations": str(social_arb_observations_path),
            "deep_liquid_universe": str(deep_universe_log_path),
            "options_liquidity_feasibility": str(options_liquidity_report_path) if options_liquidity_report_path else "disabled",
        },
        "candidate_count": len(instruments),
        "priority_count": sum(1 for item in instruments if item.get("action") in {"priority_shadow_review", "promotion_review"}),
        "research_only_count": sum(1 for item in instruments if item.get("action") == "research_only"),
        "hot_instruments": instruments[:50],
        "manual_social_instruments": manual_social[:50],
        "verifier_instruments": verifier_instruments,
        "promotion_rule": "No symbol promotion without 30 trading days and at least 10 completed shadow samples.",
        "warnings": [
            "Read-only. No broker calls are made.",
            "Social persistence is attention, not edge. Options/liquidity and shadow outcomes must agree.",
            "Current option-chain spread, volume, expiry, and affordability can veto promotion review.",
            "Small-cap squeeze names remain research-only unless separate liquidity and risk rules are written.",
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
    print("\nWeekly Hot Instruments | read-only")
    print("=" * 72)
    print(
        f"date={report['date']} lookback={report['lookback_days']}d "
        f"candidates={report['candidate_count']} priority={report['priority_count']} "
        f"research_only={report['research_only_count']}"
    )
    for item in report["hot_instruments"][:12]:
        print(
            f"{item['symbol']:<6} score={item['hot_score']:<5} action={item['action']:<22} "
            f"social_days={item['social_day_count']} slots={item['social_slot_count']} "
            f"shadow={item['shadow_completed_count']} wr={item['shadow_win_rate']} "
            f"best={item['best_shadow_return_pct']}%"
        )
    manual = report.get("manual_social_instruments") or []
    if manual:
        print("Manual social observations:")
        for item in manual[:8]:
            print(
                f"  {item['symbol']:<6} action={item['action']:<14} "
                f"sources={item['social_arb_source_count']} theme={item['social_arb_theme']}"
            )
    print("No orders placed. No settings changed.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Rank weekly hot instruments from social persistence and shadow outcomes.")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--social-log-path", type=Path, default=SOCIAL_LOG_PATH)
    parser.add_argument("--shadow-eval-log-path", type=Path, default=SHADOW_EVAL_LOG_PATH)
    parser.add_argument("--social-arb-observations-path", type=Path, default=SOCIAL_ARB_OBSERVATIONS_PATH)
    parser.add_argument("--deep-universe-log-path", type=Path, default=DEEP_UNIVERSE_LOG_PATH)
    parser.add_argument("--options-liquidity-report-path", type=Path, default=OPTIONS_LIQUIDITY_REPORT_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    report = build_report(
        social_log_path=args.social_log_path,
        shadow_eval_log_path=args.shadow_eval_log_path,
        social_arb_observations_path=args.social_arb_observations_path,
        deep_universe_log_path=args.deep_universe_log_path,
        options_liquidity_report_path=args.options_liquidity_report_path,
        days=args.days,
        today=args.date,
    )
    write_report(report, args.report_path)
    append_log(report, args.log_path)
    if args.do_print:
        print_report(report)
    else:
        print(f"Weekly hot instrument report written to {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
