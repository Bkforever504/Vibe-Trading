"""Read-only adaptive options playbook selector.

This is a shadow-only intelligence layer. It decides which options playbook
would fit the current tape and records why. It never submits orders.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
MARKET_FORCE_LOG = ROOT / "data" / "market_force_score_log.jsonl"
OPENING_RANGE_LOG = ROOT / "data" / "opening_range_breadth_log.jsonl"
RV_IV_REGIME_LOG = ROOT / "data" / "rv_iv_regime_log.jsonl"
EXPECTED_MOVE_LOG = ROOT / "data" / "zero_dte_expected_move_context_log.jsonl"
OPTIONS_HEATMAP_LOG = ROOT / "data" / "options_liquidation_heatmap_log.jsonl"
LOG_PATH = ROOT / "data" / "adaptive_options_shadow_playbook_log.jsonl"
REPORT_PATH = VIBE_HOME / "reports" / "adaptive-options-shadow-playbook.json"
DEFAULT_SYMBOLS = ["SPY", "QQQ"]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return None


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


def _latest_market_force_trend() -> str:
    rows = _read_jsonl(MARKET_FORCE_LOG)
    classification = str((rows[-1] if rows else {}).get("classification") or "").lower()
    if "bearish" in classification:
        return "bearish"
    if "bullish" in classification:
        return "bullish"
    if "mixed" in classification:
        return "mixed"
    return "unknown"


def _latest_jsonl_row(path: Path) -> dict[str, Any]:
    rows = _read_jsonl(path)
    return rows[-1] if rows else {}


def _latest_opening_range_state(symbol: str) -> str:
    row = _latest_jsonl_row(OPENING_RANGE_LOG)
    scans = row.get("scans") if isinstance(row, dict) else []
    if not isinstance(scans, list):
        return "unknown"
    for scan in scans:
        if isinstance(scan, dict) and str(scan.get("symbol") or "").upper() == symbol:
            return str(scan.get("state") or scan.get("status") or "unknown")
    return str(row.get("status") or "unknown")


def _latest_volatility_regime(symbol: str) -> str:
    row = _latest_jsonl_row(RV_IV_REGIME_LOG)
    scans = row.get("scans") if isinstance(row, dict) else []
    if isinstance(scans, list):
        for scan in scans:
            if isinstance(scan, dict) and str(scan.get("symbol") or "").upper() == symbol:
                regime = str(scan.get("regime") or scan.get("bias") or scan.get("status") or "unknown")
                if regime not in {"unavailable", "no_context", "error"}:
                    return regime
    aggregate = row.get("aggregate") if isinstance(row.get("aggregate"), dict) else {}
    return str(aggregate.get("regime") or aggregate.get("bias") or "unknown")


def _latest_expected_move_context(symbol: str) -> dict[str, Any]:
    row = _latest_jsonl_row(EXPECTED_MOVE_LOG)
    scans = row.get("scans") if isinstance(row, dict) else []
    if not isinstance(scans, list):
        return {}
    for scan in scans:
        if (
            isinstance(scan, dict)
            and str(scan.get("symbol") or "").upper() == symbol
            and scan.get("status") == "ok"
        ):
            return {
                "expected_move_pct": _safe_float(scan.get("expected_move_pct")),
                "opening_range_fraction": _safe_float(scan.get("opening_range_fraction")),
                "opening_range_bucket": str(scan.get("opening_range_bucket") or "unknown"),
                "expected_move_consumed_fraction": _safe_float(scan.get("expected_move_consumed_fraction")),
                "breakout_overshoot_fraction": _safe_float(scan.get("breakout_overshoot_fraction")),
            }
    return {}


def _latest_options_heatmap_context(symbol: str) -> dict[str, Any]:
    row = _latest_jsonl_row(OPTIONS_HEATMAP_LOG)
    results = row.get("results") if isinstance(row, dict) else []
    if not isinstance(results, list):
        return {}
    for item in results:
        if (
            isinstance(item, dict)
            and str(item.get("symbol") or "").upper() == symbol
            and item.get("status") == "ok"
        ):
            labels = item.get("condition_labels") if isinstance(item.get("condition_labels"), list) else []
            return {
                "options_heat_state": str(item.get("front_heat_state") or "unknown"),
                "options_heat_labels": [str(label) for label in labels],
                "options_heat_pc_oi": _safe_float(item.get("front_put_call_open_interest_ratio")),
                "options_heat_front_move_pct": _safe_float(item.get("front_implied_move_pct")),
            }
    return {}


def _flip_context(symbol: str) -> dict[str, Any]:
    trades = _read_json(VIBE_HOME / "flip-trades.json")
    if not isinstance(trades, list):
        return {}
    closed = [
        trade for trade in trades
        if isinstance(trade, dict)
        and str(trade.get("symbol") or "").upper() == symbol
        and trade.get("status") == "closed"
    ][-5:]
    if not closed:
        return {}
    directions = []
    wins = 0
    for trade in closed:
        strategy = str(trade.get("strategy") or "").lower()
        right = str(trade.get("right") or "").upper()
        if "bear" in strategy or right == "PUT":
            directions.append("bearish")
        elif "bull" in strategy or right == "CALL":
            directions.append("bullish")
        if _safe_float(trade.get("pnl")) > 0:
            wins += 1
    if not directions:
        return {"flip_recent_win_rate": wins / len(closed)}
    direction = max(set(directions), key=directions.count)
    return {
        "flip_recent_direction": direction,
        "flip_recent_win_rate": round(wins / len(closed), 3),
    }


def _liquidity_context(symbol: str) -> dict[str, Any]:
    report = _read_json(VIBE_HOME / "reports" / "options-liquidity-feasibility.json")
    rows = report.get("results") if isinstance(report, dict) else []
    if not isinstance(rows, list):
        return {}
    for row in rows:
        if isinstance(row, dict) and str(row.get("symbol") or "").upper() == symbol:
            criteria = row.get("criteria") if isinstance(row.get("criteria"), dict) else {}
            return {
                "liquidity_ok": bool(row.get("flip_shadow_eligible") or row.get("score", 0) >= 4),
                "credit_to_risk": _safe_float(row.get("credit_to_risk")),
                "spread_ok": bool(criteria.get("spread_ok", True)),
            }
    return {}


def build_contexts(symbols: list[str]) -> dict[str, dict[str, Any]]:
    trend = _latest_market_force_trend()
    contexts: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        symbol = symbol.upper()
        context: dict[str, Any] = {"trend": trend}
        context["opening_range_state"] = _latest_opening_range_state(symbol)
        context["volatility_regime"] = _latest_volatility_regime(symbol)
        context.update(_latest_expected_move_context(symbol))
        context.update(_latest_options_heatmap_context(symbol))
        if trend == "bearish":
            context.update({"below_vwap": True, "below_ema50": True, "bearish_orb": True})
        elif trend == "bullish":
            context.update({"above_vwap": True, "above_ema50": True, "bullish_orb": True})
        context.update(_liquidity_context(symbol))
        context.update(_flip_context(symbol))
        contexts[symbol] = context
    return contexts


def classify_market_conditions(context: dict[str, Any]) -> list[dict[str, str]]:
    trend = str(context.get("trend") or "unknown").lower()
    opening_range = str(context.get("opening_range_state") or "unknown").lower()
    volatility = str(context.get("volatility_regime") or "unknown").lower()
    liquidity_ok = bool(context.get("liquidity_ok"))
    credit_to_risk = _safe_float(context.get("credit_to_risk"))
    flip_direction = str(context.get("flip_recent_direction") or "none").lower()
    flip_win_rate = _safe_float(context.get("flip_recent_win_rate"))
    opening_range_bucket = str(context.get("opening_range_bucket") or "unknown")
    expected_move_consumed = _safe_float(context.get("expected_move_consumed_fraction"), -1.0)
    heat_state = str(context.get("options_heat_state") or "unknown")
    heat_labels = context.get("options_heat_labels") if isinstance(context.get("options_heat_labels"), list) else []
    labels: list[dict[str, str]] = []

    if trend == "bearish":
        labels.append({"label": "bearish_trend", "evidence": "market force classified bearish"})
    elif trend == "bullish":
        labels.append({"label": "bullish_trend", "evidence": "market force classified bullish"})
    elif trend == "mixed":
        labels.append({"label": "mixed_chop", "evidence": "market force classified mixed"})
    else:
        labels.append({"label": "trend_unknown", "evidence": "market force unavailable"})

    if opening_range == "below_opening_range":
        labels.append({"label": "bearish_opening_range", "evidence": "latest price below opening range"})
    elif opening_range == "above_opening_range":
        labels.append({"label": "bullish_opening_range", "evidence": "latest price above opening range"})
    elif opening_range == "inside_opening_range":
        labels.append({"label": "range_bound_opening_range", "evidence": "latest price inside opening range"})
    elif opening_range == "market_closed":
        labels.append({"label": "market_closed_context", "evidence": "latest opening-range scanner row is market_closed"})
    else:
        labels.append({"label": "opening_range_unknown", "evidence": "opening-range state unavailable"})

    if volatility in {"vol_expansion", "momentum_breakout", "expansion"}:
        labels.append({"label": "volatility_expansion", "evidence": f"rv/iv regime={volatility}"})
    elif volatility in {"premium_mean_reversion", "vol_crush", "contraction"}:
        labels.append({"label": "volatility_contraction", "evidence": f"rv/iv regime={volatility}"})
    elif volatility in {"normal", "balanced"}:
        labels.append({"label": "normal_volatility", "evidence": f"rv/iv regime={volatility}"})
    else:
        labels.append({"label": "volatility_unknown", "evidence": "rv/iv regime unavailable"})

    if opening_range_bucket != "unknown":
        labels.append({
            "label": f"expected_move_{opening_range_bucket}",
            "evidence": (
                f"opening range={_safe_float(context.get('opening_range_fraction')):.1%} "
                f"of implied daily move"
            ),
        })
    if expected_move_consumed >= 0:
        if expected_move_consumed < 0.50:
            consumed_label = "expected_move_under_half_consumed"
        elif expected_move_consumed <= 1.00:
            consumed_label = "expected_move_half_to_full_consumed"
        else:
            consumed_label = "expected_move_over_full_consumed"
        labels.append({
            "label": consumed_label,
            "evidence": f"displacement consumed {expected_move_consumed:.1%} of implied daily move",
        })

    if heat_state != "unknown":
        labels.append({
            "label": f"options_heat_{heat_state}",
            "evidence": f"option-chain heat state={heat_state}",
        })
    if "spot_inside_heat_band" in heat_labels:
        labels.append({"label": "spot_inside_options_heat_band", "evidence": "spot is near a high OI/volume zone"})
    if "put_oi_pressure" in heat_labels:
        labels.append({"label": "put_oi_pressure", "evidence": "front-expiry put/call OI ratio elevated"})
    elif "call_oi_pressure" in heat_labels:
        labels.append({"label": "call_oi_pressure", "evidence": "front-expiry call OI pressure elevated"})

    labels.append(
        {"label": "liquid_options" if liquidity_ok else "options_liquidity_blocked",
         "evidence": "options liquidity gate passed" if liquidity_ok else "options liquidity gate failed or missing"}
    )
    if credit_to_risk >= 0.25:
        labels.append({"label": "strong_credit", "evidence": f"credit_to_risk={credit_to_risk:.2f}"})
    elif credit_to_risk >= 0.20:
        labels.append({"label": "acceptable_credit", "evidence": f"credit_to_risk={credit_to_risk:.2f}"})
    else:
        labels.append({"label": "thin_credit", "evidence": f"credit_to_risk={credit_to_risk:.2f}"})

    if flip_direction in {"bearish", "bullish"} and flip_win_rate >= 0.6:
        labels.append({"label": f"flip_{flip_direction}_confirmed", "evidence": f"recent Flip win rate={flip_win_rate:.1%}"})
    elif flip_direction in {"bearish", "bullish"}:
        labels.append({"label": f"flip_{flip_direction}_unconfirmed", "evidence": f"recent Flip win rate={flip_win_rate:.1%}"})
    else:
        labels.append({"label": "flip_direction_unknown", "evidence": "no recent directional Flip evidence"})
    return labels


def summarize_conditions(conditions: list[dict[str, str]]) -> dict[str, Any]:
    labels = [item["label"] for item in conditions]
    if "bearish_trend" in labels and "bearish_opening_range" in labels:
        primary = "bearish_trend"
    elif "bullish_trend" in labels and "bullish_opening_range" in labels:
        primary = "bullish_trend"
    elif "range_bound_opening_range" in labels or "mixed_chop" in labels:
        primary = "mixed_chop"
    elif "bearish_trend" in labels:
        primary = "bearish_bias"
    elif "bullish_trend" in labels:
        primary = "bullish_bias"
    else:
        primary = "unknown"
    return {
        "primary_regime": primary,
        "labels": labels,
        "tradeable": "options_liquidity_blocked" not in labels and "market_closed_context" not in labels,
    }


def evaluate_symbol_playbook(symbol: str, context: dict[str, Any]) -> dict[str, Any]:
    symbol = symbol.upper()
    trend = str(context.get("trend") or "unknown").lower()
    credit_to_risk = _safe_float(context.get("credit_to_risk"))
    liquidity_ok = bool(context.get("liquidity_ok"))
    flip_direction = str(context.get("flip_recent_direction") or "none").lower()
    flip_win_rate = _safe_float(context.get("flip_recent_win_rate"))
    below_vwap = bool(context.get("below_vwap"))
    below_ema50 = bool(context.get("below_ema50"))
    bearish_orb = bool(context.get("bearish_orb"))
    above_vwap = bool(context.get("above_vwap"))
    above_ema50 = bool(context.get("above_ema50"))
    bullish_orb = bool(context.get("bullish_orb"))
    range_bound = bool(context.get("range_bound"))
    conditions = classify_market_conditions(context)
    condition_summary = summarize_conditions(conditions)

    blockers: list[str] = []
    evidence: list[str] = []
    selected = "none"
    action = "stand_aside"
    primary_reason = "No proven playbook matches the current evidence."

    if not liquidity_ok:
        blockers.append("Options liquidity gate failed")

    bearish_confirmed = trend == "bearish" and below_vwap and below_ema50 and bearish_orb
    bullish_confirmed = trend == "bullish" and above_vwap and above_ema50 and bullish_orb
    flip_bearish_confirmed = flip_direction == "bearish" and flip_win_rate >= 0.6
    flip_bullish_confirmed = flip_direction == "bullish" and flip_win_rate >= 0.6

    if bearish_confirmed:
        evidence.extend(["bearish trend", "below VWAP", "below 50EMA", "bearish opening range"])
        if flip_bearish_confirmed and liquidity_ok:
            selected = "long_put"
            action = "shadow_watch_bearish_long_put"
            primary_reason = "bearish tape favors directional debit exposure"
        elif credit_to_risk >= 0.20 and liquidity_ok:
            selected = "call_credit_spread"
            action = "shadow_watch_call_credit_spread"
            primary_reason = "bearish tape plus acceptable credit/risk favors defined-risk short call premium"
        else:
            if not flip_bearish_confirmed:
                blockers.append("Flip evidence does not confirm bearish direction")
            if credit_to_risk < 0.20:
                blockers.append("Call credit spread credit/risk is below minimum")
    elif bullish_confirmed:
        evidence.extend(["bullish trend", "above VWAP", "above 50EMA", "bullish opening range"])
        if credit_to_risk >= 0.20 and liquidity_ok:
            selected = "put_credit_spread"
            action = "shadow_watch_put_credit_spread"
            primary_reason = "bullish tape plus acceptable credit/risk favors defined-risk short put premium"
        elif flip_bullish_confirmed and liquidity_ok:
            selected = "long_call"
            action = "shadow_watch_bullish_long_call"
            primary_reason = "bullish tape favors directional debit exposure"
        else:
            if credit_to_risk < 0.20:
                blockers.append("Put credit spread credit/risk is below minimum")
            if not flip_bullish_confirmed:
                blockers.append("Flip evidence does not confirm bullish direction")
    elif range_bound and credit_to_risk >= 0.25 and liquidity_ok:
        selected = "iron_condor"
        action = "shadow_watch_iron_condor"
        primary_reason = "range evidence plus sufficient premium favors neutral defined-risk income"
        evidence.append("range-bound tape")
    else:
        blockers.append("Market regime is unclear or mixed")

    if "market_closed_context" in condition_summary["labels"]:
        selected = "none"
        action = "stand_aside"
        primary_reason = "Market is closed; no adaptive options playbook is actionable."
        blockers.append("Market is closed")
    elif "options_liquidity_blocked" in condition_summary["labels"]:
        selected = "none"
        action = "stand_aside"
        primary_reason = "Options liquidity is insufficient for an adaptive options playbook."

    return {
        "symbol": symbol,
        "status": "ok",
        "mode": "shadow_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "selected_playbook": selected,
        "action": action,
        "market_conditions": conditions,
        "condition_summary": condition_summary,
        "explanation": {
            "primary_reason": primary_reason,
            "evidence": evidence,
            "blockers": blockers,
            "next_action": "log forward outcome before any execution discussion",
        },
        "inputs": {
            "trend": trend,
            "credit_to_risk": credit_to_risk,
            "liquidity_ok": liquidity_ok,
            "flip_recent_direction": flip_direction,
            "flip_recent_win_rate": flip_win_rate,
            "opening_range_fraction": _safe_float(context.get("opening_range_fraction")),
            "opening_range_bucket": context.get("opening_range_bucket"),
            "expected_move_consumed_fraction": _safe_float(context.get("expected_move_consumed_fraction")),
            "breakout_overshoot_fraction": _safe_float(context.get("breakout_overshoot_fraction")),
            "options_heat_state": context.get("options_heat_state"),
            "options_heat_labels": context.get("options_heat_labels"),
            "options_heat_pc_oi": _safe_float(context.get("options_heat_pc_oi")),
            "options_heat_front_move_pct": _safe_float(context.get("options_heat_front_move_pct")),
        },
    }


def build_report(symbols: list[str] | None = None, contexts: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    symbols = symbols or DEFAULT_SYMBOLS
    contexts = contexts if contexts is not None else build_contexts([symbol.upper() for symbol in symbols])
    rows = [evaluate_symbol_playbook(symbol, contexts.get(symbol.upper(), {})) for symbol in symbols]
    return {
        "date": date.today().isoformat(),
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "adaptive_options_shadow_playbook",
        "mode": "shadow_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "symbol_count": len(rows),
        "actionable_shadow_count": sum(1 for row in rows if row.get("selected_playbook") != "none"),
        "rows": rows,
        "warnings": [
            "Read-only adaptive playbook selector. No broker orders are wired.",
            "Directional options playbooks require forward evidence before execution.",
        ],
    }


def append_log(report: dict[str, Any], log_path: Path = LOG_PATH) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, separators=(",", ":")) + "\n"
    try:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(payload)
    except OSError:
        fallback = REPORT_PATH.parent / (
            f"{log_path.stem}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{os.getpid()}{log_path.suffix}"
        )
        try:
            fallback.parent.mkdir(parents=True, exist_ok=True)
            with fallback.open("a", encoding="utf-8") as f:
                f.write(payload)
        except OSError:
            return


def write_report(report: dict[str, Any], report_path: Path = REPORT_PATH) -> Path:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, indent=2) + "\n"
    temp = report_path.with_suffix(report_path.suffix + f".tmp-{os.getpid()}-{datetime.now(timezone.utc).timestamp()}")
    try:
        temp.write_text(payload, encoding="utf-8")
        os.replace(temp, report_path)
        return report_path
    except OSError:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        fallback = report_path.with_name(
            f"{report_path.stem}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}{report_path.suffix}"
        )
        try:
            fallback.write_text(payload, encoding="utf-8")
            return fallback
        except OSError:
            return report_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build read-only adaptive options playbook report.")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
    report = build_report(symbols=symbols)
    append_log(report, args.log_path)
    write_report(report, args.report_path)
    print(f"Adaptive options shadow playbook logged to {args.log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
