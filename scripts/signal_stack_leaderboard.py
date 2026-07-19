#!/usr/bin/env python3
"""Build a read-only leaderboard across bots, shadow loggers, and context scanners."""
from __future__ import annotations

import argparse
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_DIR = VIBE_HOME / "reports"
REPORT_PATH = REPORT_DIR / "signal-stack-leaderboard.json"
REGISTRY_PATH = ROOT / "research" / "signal_registry.json"


JSONL_SOURCES = [
    ("RSI-2 QQQ", "shadow_strategy", ROOT / "data" / "rsi2_shadow_log.jsonl"),
    ("KAMA QQQ", "shadow_strategy", ROOT / "data" / "kama_shadow_log.jsonl"),
    ("Williams %R", "shadow_strategy", ROOT / "data" / "williams_r_shadow_log.jsonl"),
    ("Momentum Rotation", "shadow_strategy", ROOT / "data" / "momentum_shadow_log.jsonl"),
    ("QQQ/GLD Rotation", "shadow_strategy", ROOT / "data" / "qqq_gld_shadow_log.jsonl"),
    ("TTM Squeeze", "shadow_strategy", ROOT / "data" / "ttm_squeeze_shadow_log.jsonl"),
    ("WaveTrend", "shadow_strategy", ROOT / "data" / "wavetrend_shadow_log.jsonl"),
    ("SMC", "shadow_strategy", ROOT / "data" / "smc_shadow_log.jsonl"),
    ("Premarket EMA Retest", "shadow_strategy", ROOT / "data" / "premarket_ema_retest_shadow_log.jsonl"),
    ("Flip Shadow Candidates", "shadow_strategy", ROOT / "data" / "flip_shadow_candidates_log.jsonl"),
    ("GEX Scanner", "context_scanner", ROOT / "data" / "gex_scan_log.jsonl"),
    ("IVR Scanner", "context_scanner", ROOT / "data" / "iv_history_log.jsonl"),
    ("IVR Quality", "review_layer", ROOT / "data" / "ivr_quality_report_log.jsonl"),
    ("RV/IV Regime", "context_scanner", ROOT / "data" / "rv_iv_regime_log.jsonl"),
    ("Opening Range Breadth", "context_scanner", ROOT / "data" / "opening_range_breadth_log.jsonl"),
    ("Relative Volume", "context_scanner", ROOT / "data" / "relative_volume_scan_log.jsonl"),
    ("SEC Insider Buying", "context_scanner", ROOT / "data" / "sec_insider_buying_log.jsonl"),
    ("Market Force Score", "context_scanner", ROOT / "data" / "market_force_score_log.jsonl"),
    ("Distribution Days", "context_scanner", ROOT / "data" / "distribution_day_log.jsonl"),
    ("Market Breadth", "context_scanner", ROOT / "data" / "market_breadth_uptrend_log.jsonl"),
    ("Sector Rotation", "context_scanner", ROOT / "data" / "sector_rotation_rank_log.jsonl"),
    ("Portfolio Concentration", "risk_layer", ROOT / "data" / "portfolio_concentration_log.jsonl"),
    ("Exposure Coach", "review_layer", ROOT / "data" / "exposure_coach_log.jsonl"),
    ("Bot Status Snapshot", "review_layer", ROOT / "data" / "bot_status_snapshot_log.jsonl"),
    ("Regime Memory", "review_layer", ROOT / "data" / "regime_memory_log.jsonl"),
    ("Rejected Trade Intelligence", "review_layer", ROOT / "data" / "rejected_trade_intelligence_log.jsonl"),
    ("Needs Review Queue", "review_layer", ROOT / "data" / "needs_review_queue_log.jsonl"),
    ("Closed Trade Postmortem", "review_layer", ROOT / "data" / "closed_trade_postmortem_log.jsonl"),
    ("Daily Outcome Review", "review_layer", ROOT / "data" / "daily_outcome_review_log.jsonl"),
    ("Challenge Account Simulator", "review_layer", ROOT / "data" / "challenge_account_simulator_log.jsonl"),
    ("Position Sizing Sanity", "risk_layer", ROOT / "data" / "position_sizing_sanity_log.jsonl"),
    ("PreOpen Sentiment", "context_scanner", ROOT / "data" / "preopen_sentiment_log.jsonl"),
    ("Social Trending", "context_scanner", ROOT / "data" / "social_trending_symbols_log.jsonl"),
    ("MoonDev Liquidation Context", "crypto_context", ROOT / "data" / "moondev_liquidation_context_log.jsonl"),
    ("Limitless Markets", "prediction_market_context", ROOT / "data" / "limitless_market_scan_log.jsonl"),
    ("Prediction Microstructure", "prediction_market_context", ROOT / "data" / "prediction_market_microstructure_log.jsonl"),
    ("PMXT Schema Probe", "prediction_market_context", ROOT / "data" / "pmxt_market_schema_probe_log.jsonl"),
]


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    return value


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) == 10:
        text = f"{text}T00:00:00Z"
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _read_jsonl(path: Path) -> tuple[list[dict[str, Any]], int]:
    if not path.exists():
        return [], 0
    rows: list[dict[str, Any]] = []
    bad = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            bad += 1
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows, bad


def _flatten_values(value: Any, key_hint: str = "") -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            out.extend(_flatten_values(child, str(key)))
    elif isinstance(value, list):
        for child in value:
            out.extend(_flatten_values(child, key_hint))
    else:
        out.append((key_hint, value))
    return out


def _extract_confidences(row: dict[str, Any]) -> list[float]:
    values = []
    for key, value in _flatten_values(row):
        if key in {"confidence", "score"}:
            parsed = _safe_float(value)
            if parsed is not None and 0 <= parsed <= 10:
                values.append(parsed)
    return values


def _extract_actions(row: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    for key, value in _flatten_values(row):
        if key == "action" and value:
            actions.append(str(value).lower())
    return actions


def _row_timestamp(row: dict[str, Any]) -> datetime | None:
    for key in ("timestamp", "generated_at", "scanned_at", "ts", "created_at", "opened_at", "entry_date", "date"):
        parsed = _parse_dt(row.get(key))
        if parsed:
            return parsed
    return None


def _freshness(latest: datetime | None, now: datetime) -> dict[str, Any]:
    if latest is None:
        return {"status": "missing", "age_days": None}
    age_days = max(0.0, (now - latest).total_seconds() / 86400)
    if age_days <= 1.5:
        status = "fresh"
    elif age_days <= 7:
        status = "aging"
    else:
        status = "stale"
    return {"status": status, "age_days": round(age_days, 2)}


def _max_drawdown_from_pnls(pnls: list[float]) -> float | None:
    if not pnls:
        return None
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)
    return round(max_dd, 2)


def _rank_score(item: dict[str, Any]) -> float:
    points = 0.0
    if item["freshness"]["status"] == "fresh":
        points += 2
    elif item["freshness"]["status"] == "aging":
        points += 1
    points += min(item.get("sample_count", 0), 30) / 10
    confidence = item.get("avg_confidence")
    if isinstance(confidence, (int, float)):
        points += confidence / 2
    pnl = item.get("total_pnl")
    if isinstance(pnl, (int, float)):
        points += max(-3.0, min(3.0, pnl / 500.0))
    if item.get("execution_mode") in {"live", "paper"}:
        points += 1
    if item.get("blocked_count", 0):
        points -= min(item["blocked_count"], 10) / 5
    return round(points, 3)


def _summarize_jsonl_source(name: str, category: str, path: Path, now: datetime) -> dict[str, Any]:
    rows, bad = _read_jsonl(path)
    legacy_excluded = 0
    if name == "Flip Shadow Candidates":
        trusted = [
            row for row in rows
            if int(row.get("schema_version") or 0) >= 2
            and row.get("data_quality") == "current_session_lifecycle"
        ]
        legacy_excluded = len(rows) - len(trusted)
        rows = trusted
    latest = max((_row_timestamp(row) for row in rows), default=None)
    confidences = [value for row in rows for value in _extract_confidences(row)]
    if rows and rows[-1].get("provider") == "market_force_score":
        top_level_confidence = _safe_float(rows[-1].get("confidence"))
        confidences = [top_level_confidence] if top_level_confidence is not None else []
    actions = [action for row in rows for action in _extract_actions(row)]
    entry_like = [
        action for action in actions
        if any(token in action for token in ("enter", "buy", "sell", "short", "selected", "hold_qqq", "hold_long"))
        and "flat" not in action
    ]
    modes = [str(row.get("execution_mode") or row.get("mode") or "").lower() for row in rows]
    execution_mode = next((mode for mode in reversed(modes) if mode), "unknown")
    item = {
        "name": name,
        "category": category,
        "source_path": str(path),
        "sample_count": len(rows),
        "bad_json_lines": bad,
        "latest_at": latest.isoformat().replace("+00:00", "Z") if latest else None,
        "freshness": _freshness(latest, now),
        "execution_mode": execution_mode,
        "avg_confidence": round(sum(confidences) / len(confidences), 2) if confidences else None,
        "signal_count": len(entry_like),
        "flat_count": sum(1 for action in actions if "flat" in action),
        "blocked_count": 0,
        "total_pnl": None,
        "win_rate": None,
        "max_drawdown_dollars": None,
        "notes": [],
    }
    if not rows:
        item["notes"].append("No log rows yet.")
    if legacy_excluded:
        item["notes"].append(
            f"Excluded {legacy_excluded} legacy rows without complete current-session lifecycles."
        )
    if category.endswith("context") or category == "context_scanner":
        item["notes"].append("Context only; not an execution signal.")
    item["rank_score"] = _rank_score(item)
    return item


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _registry_signal(signal_id: str) -> dict[str, Any]:
    payload = _load_json(REGISTRY_PATH)
    signals = payload.get("signals") if isinstance(payload, dict) else []
    if not isinstance(signals, list):
        return {}
    for signal in signals:
        if isinstance(signal, dict) and signal.get("id") == signal_id:
            return signal
    return {}


def _trade_date(trade: dict[str, Any]) -> str:
    return str(trade.get("entry_date") or trade.get("opened_at") or trade.get("date") or "")


def _performance_from_trades(trades: list[dict[str, Any]]) -> dict[str, Any]:
    pnls = [_safe_float(trade.get("pnl")) for trade in trades if isinstance(trade, dict)]
    pnls = [pnl for pnl in pnls if pnl is not None]
    return {
        "sample_count": len(trades),
        "total_pnl": round(sum(pnls), 2) if pnls else None,
        "win_rate": round(sum(1 for pnl in pnls if pnl > 0) / len(pnls), 4) if pnls else None,
        "max_drawdown_dollars": _max_drawdown_from_pnls(pnls),
    }


def _summarize_flip_trades(now: datetime) -> dict[str, Any]:
    path = VIBE_HOME / "flip-trades.json"
    trades = _load_json(path)
    if not isinstance(trades, list):
        trades = []
    pnls = [_safe_float(trade.get("pnl")) for trade in trades if isinstance(trade, dict)]
    pnls = [pnl for pnl in pnls if pnl is not None]
    closed = [trade for trade in trades if isinstance(trade, dict) and trade.get("status") == "closed"]
    latest = max((_row_timestamp(trade) for trade in trades if isinstance(trade, dict)), default=None)
    registry = _registry_signal("flip_bot")
    item = {
        "name": "Flip Bot",
        "category": "alpaca_options_execution",
        "source_path": str(path),
        "sample_count": len(trades),
        "closed_count": len(closed),
        "open_count": sum(1 for trade in trades if isinstance(trade, dict) and trade.get("status") == "open"),
        "latest_at": latest.isoformat().replace("+00:00", "Z") if latest else None,
        "freshness": _freshness(latest, now),
        "execution_mode": "paper_or_live_alpaca",
        "avg_confidence": None,
        "signal_count": len(trades),
        "blocked_count": 0,
        "total_pnl": round(sum(pnls), 2) if pnls else None,
        "win_rate": round(sum(1 for pnl in pnls if pnl > 0) / len(pnls), 4) if pnls else None,
        "max_drawdown_dollars": _max_drawdown_from_pnls(pnls),
        "notes": ["Execution-capable; governed by Alpaca execution guard and portfolio kill switch."],
    }
    config_change_date = registry.get("config_change_date")
    post_config_start_date = registry.get("post_config_start_date") or config_change_date
    if config_change_date:
        item["config_change_date"] = config_change_date
    if post_config_start_date:
        post_config_trades = [
            trade for trade in trades
            if isinstance(trade, dict) and _trade_date(trade) >= str(post_config_start_date)
        ]
        post_config = _performance_from_trades(post_config_trades)
        post_config.update({
            "label": registry.get("post_config_label") or "post_risk_fix",
            "start_date": post_config_start_date,
        })
        item["post_config"] = post_config
        if item.get("total_pnl") is not None and post_config.get("total_pnl") is not None:
            if float(item["total_pnl"]) < float(post_config["total_pnl"]):
                item["notes"].append("All-time PnL includes pre-fix risk artifact.")
    item["rank_score"] = _rank_score(item)
    return item


def _summarize_iwm_trades(now: datetime) -> dict[str, Any]:
    path = VIBE_HOME / "options-trades.json"
    payload = _load_json(path)
    trades = payload.get("trades") if isinstance(payload, dict) else []
    if not isinstance(trades, list):
        trades = []
    confidences = []
    for trade in trades:
        if not isinstance(trade, dict):
            continue
        score = ((trade.get("candidate_confidence") or {}) if isinstance(trade.get("candidate_confidence"), dict) else {}).get("score")
        parsed = _safe_float(score)
        if parsed is not None:
            confidences.append(parsed)
    latest = max((_row_timestamp(trade) for trade in trades if isinstance(trade, dict)), default=None)
    item = {
        "name": "IWM Options Bot",
        "category": "alpaca_options_execution",
        "source_path": str(path),
        "sample_count": len(trades),
        "closed_count": sum(1 for trade in trades if isinstance(trade, dict) and trade.get("status") == "closed"),
        "open_count": sum(1 for trade in trades if isinstance(trade, dict) and trade.get("status") == "open"),
        "latest_at": latest.isoformat().replace("+00:00", "Z") if latest else None,
        "freshness": _freshness(latest, now),
        "execution_mode": "paper_or_live_alpaca",
        "avg_confidence": round(sum(confidences) / len(confidences), 2) if confidences else None,
        "signal_count": len(trades),
        "blocked_count": 0,
        "total_pnl": None,
        "win_rate": None,
        "max_drawdown_dollars": None,
        "notes": ["Open/closed spread lifecycle tracked; realized P&L not fully normalized in this file yet."],
    }
    item["rank_score"] = _rank_score(item)
    return item


def _guard_block_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in (VIBE_HOME / "guard-blocks.jsonl", VIBE_HOME / "kalshi-guard-blocks.jsonl"):
        rows, _bad = _read_jsonl(path)
        for row in rows:
            details = row.get("details") if isinstance(row.get("details"), dict) else {}
            bot = str(details.get("bot") or ("kalshi" if "kalshi" in path.name else "unknown"))
            counts[bot] = counts.get(bot, 0) + 1
    return counts


def build_leaderboard(now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    items = [
        _summarize_flip_trades(now),
        _summarize_iwm_trades(now),
    ]
    items.extend(_summarize_jsonl_source(name, category, path, now) for name, category, path in JSONL_SOURCES)
    block_counts = _guard_block_counts()
    for item in items:
        lowered = item["name"].lower()
        if "flip" in lowered:
            item["blocked_count"] = block_counts.get("flip", 0)
        elif "iwm" in lowered or "options" in lowered:
            item["blocked_count"] = block_counts.get("options", 0)
        elif "kalshi" in lowered:
            item["blocked_count"] = block_counts.get("kalshi", 0)
        item["rank_score"] = _rank_score(item)

    ranked = sorted(items, key=lambda item: item["rank_score"], reverse=True)
    return {
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "provider": "signal_stack_leaderboard",
        "mode": "read_only",
        "execution_enabled": False,
        "item_count": len(ranked),
        "items": ranked,
        "warnings": [
            "Leaderboard is an observability layer, not an execution gate.",
            "P&L and drawdown are only shown when source logs contain normalized outcomes.",
            "Context scanners are ranked for freshness/coverage only; they are not trade systems.",
        ],
    }


def write_report(report: dict[str, Any], path: Path = REPORT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=_json_default), encoding="utf-8")
    return path


def print_report(report: dict[str, Any]) -> None:
    print("\nSignal Stack Leaderboard | read-only")
    print("=" * 96)
    for item in report["items"]:
        pnl = "-" if item.get("total_pnl") is None else f"${item['total_pnl']:,.2f}"
        wr = "-" if item.get("win_rate") is None else f"{item['win_rate'] * 100:.1f}%"
        conf = "-" if item.get("avg_confidence") is None else f"{item['avg_confidence']:.1f}"
        print(
            f"{item['name']:<22} score={item['rank_score']:<5} "
            f"rows={item['sample_count']:<3} signals={item['signal_count']:<3} "
            f"conf={conf:<4} pnl={pnl:<12} wr={wr:<6} "
            f"fresh={item['freshness']['status']:<7} mode={item['execution_mode']}"
        )
    print(f"\nJSON: {REPORT_PATH}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    report = build_leaderboard()
    print_report(report)
    if not args.no_write:
        write_report(report, args.report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
