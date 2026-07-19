"""Read-only Market Force Score aggregator.

Turns the scanner stack into a single daily force tape:
- trend force from opening-range breadth
- level/structure force from GEX
- momentum force from TTM/WaveTrend/SMC
- volatility/regime context from VIX/IVR
- narrative/participation from pre-open sentiment, social, and relative volume

This is observability only. It never places orders and must not become an
execution gate until forward outcome data proves value.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
LOG_PATH = ROOT / "data" / "market_force_score_log.jsonl"
REPORT_PATH = VIBE_HOME / "reports" / "market-force-score.json"

SOURCE_PATHS = {
    "opening_range": ROOT / "data" / "opening_range_breadth_log.jsonl",
    "gex": ROOT / "data" / "gex_scan_log.jsonl",
    "ivr": ROOT / "data" / "iv_history_log.jsonl",
    "rv_iv_regime": ROOT / "data" / "rv_iv_regime_log.jsonl",
    "hurst_regime": ROOT / "data" / "hurst_regime_log.jsonl",
    "preopen_sentiment": ROOT / "data" / "preopen_sentiment_log.jsonl",
    "social_trending": ROOT / "data" / "social_trending_symbols_log.jsonl",
    "relative_volume": ROOT / "data" / "relative_volume_scan_log.jsonl",
    "distribution_days": ROOT / "data" / "distribution_day_log.jsonl",
    "market_breadth": ROOT / "data" / "market_breadth_uptrend_log.jsonl",
    "sector_rotation": ROOT / "data" / "sector_rotation_rank_log.jsonl",
    "ttm_squeeze": ROOT / "data" / "ttm_squeeze_shadow_log.jsonl",
    "wavetrend": ROOT / "data" / "wavetrend_shadow_log.jsonl",
    "smc": ROOT / "data" / "smc_shadow_log.jsonl",
}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
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


def _row_date(row: dict[str, Any]) -> str:
    for key in ("date", "timestamp", "created_at", "ts"):
        value = row.get(key)
        if value:
            return str(value)[:10]
    return ""


def latest_for_day(path: Path, day: str) -> dict[str, Any] | None:
    matches = [row for row in _read_jsonl(path) if _row_date(row) == day]
    return matches[-1] if matches else None


def _force(name: str, score: float, status: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    if score > 0:
        direction = "bullish"
    elif score < 0:
        direction = "bearish"
    else:
        direction = "neutral"
    return {
        "name": name,
        "score": round(score, 3),
        "direction": direction,
        "status": status,
        "evidence": evidence or {},
    }


def trend_force(opening_range: dict[str, Any] | None) -> dict[str, Any]:
    if not opening_range:
        return _force("trend", 0, "missing")
    agg = opening_range.get("aggregate") if isinstance(opening_range.get("aggregate"), dict) else {}
    bias = str(agg.get("bias") or "")
    if bias == "bullish_breadth":
        score = 2.0
    elif bias == "bearish_breadth":
        score = -2.0
    else:
        score = 0.0
    return _force("trend", score, "ok", agg)


def gex_force(gex: dict[str, Any] | None, trend_score: float) -> dict[str, Any]:
    if not gex:
        return _force("levels_gex", 0, "missing")
    scans = [
        row for row in gex.get("scans", [])
        if isinstance(row, dict)
        and row.get("status") == "ok"
        and row.get("expiry_filter") == "0dte"
        and row.get("size_source") == "open_interest"
        and float(row.get("open_interest_coverage") or 0.0) >= 0.60
    ]
    if not scans:
        return _force("levels_gex", 0, "unavailable", {"reason": "no provenance-qualified 0dte scans"})
    negative = sum(1 for row in scans if row.get("net_gex_regime") == "negative")
    positive = sum(1 for row in scans if row.get("net_gex_regime") == "positive")
    # Negative gamma amplifies the existing trend tape. Positive gamma dampens.
    if negative > positive and trend_score:
        score = 1.0 if trend_score > 0 else -1.0
        status = "trend_amplifier"
    elif positive > negative:
        score = 0.0
        status = "range_damper"
    else:
        score = 0.0
        status = "mixed"
    return _force("levels_gex", score, status, {"negative_gamma": negative, "positive_gamma": positive})


def _action_score(action: str) -> float:
    action = action.lower()
    if any(token in action for token in ("enter_long", "hold_long", "bull", "long")):
        return 1.0
    if any(token in action for token in ("enter_short", "hold_short", "bear", "short")):
        return -1.0
    return 0.0


def _momentum_row_score(row: dict[str, Any] | None) -> tuple[float, dict[str, Any]]:
    if not row:
        return 0.0, {"status": "missing"}
    scores = []
    evidence: dict[str, Any] = {}
    for key in ("primary", "comparison", "primary_setup", "comparison_setup"):
        section = row.get(key)
        if isinstance(section, dict):
            action = str(section.get("action") or "")
            scores.append(_action_score(action))
            evidence[key] = action
    if not scores:
        action = str(row.get("action") or "")
        scores.append(_action_score(action))
        evidence["action"] = action
    total = sum(scores)
    return max(-1.0, min(1.0, total)), evidence


def momentum_force(ttm: dict[str, Any] | None, wavetrend: dict[str, Any] | None, smc: dict[str, Any] | None) -> dict[str, Any]:
    parts = {
        "ttm": _momentum_row_score(ttm),
        "wavetrend": _momentum_row_score(wavetrend),
        "smc": _momentum_row_score(smc),
    }
    available = {name: value for name, value in parts.items() if value[1].get("status") != "missing"}
    if not available:
        return _force("momentum", 0, "missing")
    score = sum(value[0] for value in available.values())
    score = max(-2.0, min(2.0, score))
    return _force("momentum", score, "ok", {name: value[1] for name, value in parts.items()})


def volatility_force(ivr: dict[str, Any] | None, vix_context: dict[str, Any] | None = None) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    score = 0.0
    status = "ok"
    if vix_context:
        evidence["vix"] = vix_context
        if vix_context.get("regime") == "panic":
            score -= 1.0
            status = "panic_veto_context"
        elif vix_context.get("regime") == "elevated":
            score += 0.5
    if ivr:
        scans = [row for row in ivr.get("scans", []) if isinstance(row, dict)]
        ivrs = [float(row["ivr"]) for row in scans if row.get("ivr") is not None]
        if ivrs:
            avg_ivr = sum(ivrs) / len(ivrs)
            evidence["avg_ivr"] = round(avg_ivr, 2)
            if avg_ivr >= 50:
                score += 0.5
            elif avg_ivr < 25:
                score -= 0.5
        else:
            evidence["ivr_status"] = "accumulating"
    if not ivr and not vix_context:
        return _force("volatility", 0, "missing")
    return _force("volatility", score, status, evidence)


def rv_iv_force(rv_iv: dict[str, Any] | None) -> dict[str, Any]:
    if not rv_iv:
        return _force("rv_iv_regime", 0, "missing")
    aggregate = rv_iv.get("aggregate") if isinstance(rv_iv.get("aggregate"), dict) else {}
    bias = str(aggregate.get("bias") or "")
    raw_score = float(aggregate.get("score") or 0.0)
    # Keep this as context until forward evidence proves it deserves more weight.
    score = max(-0.75, min(0.75, raw_score * 0.75))
    if bias == "momentum_breakout":
        status = "momentum_context"
    elif bias == "premium_mean_reversion":
        status = "premium_context"
    elif bias == "stand_aside_or_confirm":
        status = "balanced_context"
    else:
        status = str(aggregate.get("status") or "unavailable")
    return _force("rv_iv_regime", score, status, aggregate)


def hurst_force(hurst_regime: dict[str, Any] | None) -> dict[str, Any]:
    if not hurst_regime:
        return _force("hurst_regime", 0, "missing")
    aggregate = hurst_regime.get("aggregate") if isinstance(hurst_regime.get("aggregate"), dict) else {}
    bias = str(aggregate.get("bias") or "")
    if bias == "momentum_trend_family":
        status = "momentum_family_context"
    elif bias == "mean_reversion_family":
        status = "mean_reversion_family_context"
    elif bias == "stand_aside_or_confirm":
        status = "random_walk_context"
    else:
        status = str(aggregate.get("status") or "unavailable")
    # Hurst is not directional. Keep score neutral until outcome data proves
    # whether it should route strategy families.
    return _force("hurst_regime", 0, status, aggregate)


def narrative_force(preopen: dict[str, Any] | None, social: dict[str, Any] | None, relvol: dict[str, Any] | None) -> dict[str, Any]:
    score = 0.0
    evidence: dict[str, Any] = {}
    if preopen:
        aggregate = preopen.get("aggregate") if isinstance(preopen.get("aggregate"), dict) else {}
        bias = str(aggregate.get("bias") or "")
        evidence["preopen_bias"] = bias
        if bias == "bullish":
            score += 1.0
        elif bias == "bearish":
            score -= 1.0
    if relvol:
        unusual = [row for row in relvol.get("unusual_symbols", []) if isinstance(row, dict)]
        changes = [float(row.get("price_change_pct") or 0.0) for row in unusual]
        evidence["relative_volume_unusual_count"] = len(unusual)
        if changes:
            avg_change = sum(changes) / len(changes)
            evidence["relative_volume_avg_change_pct"] = round(avg_change, 3)
            if avg_change > 1:
                score += 0.5
            elif avg_change < -1:
                score -= 0.5
    if social:
        symbols = [row for row in social.get("symbols", []) if isinstance(row, dict)]
        watch = [row.get("symbol") for row in symbols if row.get("action") == "watch_context"]
        evidence["social_watch_context_count"] = len(watch)
        evidence["social_watch_context_symbols"] = watch[:10]
    if not any((preopen, social, relvol)):
        return _force("narrative", 0, "missing")
    return _force("narrative", max(-1.5, min(1.5, score)), "ok", evidence)


def institutional_force(distribution_days: dict[str, Any] | None) -> dict[str, Any]:
    if not distribution_days:
        return _force("institutional", 0, "missing")
    aggregate = distribution_days.get("aggregate") if isinstance(distribution_days.get("aggregate"), dict) else {}
    regime = str(aggregate.get("regime") or "")
    scores = {
        "normal": 0.0,
        "caution": -0.75,
        "high": -1.5,
        "severe": -2.0,
    }
    score = scores.get(regime, 0.0)
    return _force("institutional", score, "ok", aggregate)


def breadth_force(market_breadth: dict[str, Any] | None) -> dict[str, Any]:
    if not market_breadth:
        return _force("breadth", 0, "missing")
    breadth = market_breadth.get("breadth") if isinstance(market_breadth.get("breadth"), dict) else {}
    score = float(market_breadth.get("force_score") or 0.0)
    return _force("breadth", score, "ok" if breadth else "unavailable", breadth)


def sector_rotation_force(sector_rotation: dict[str, Any] | None) -> dict[str, Any]:
    if not sector_rotation:
        return _force("sector_rotation", 0, "missing")
    rotation = sector_rotation.get("rotation") if isinstance(sector_rotation.get("rotation"), dict) else {}
    score = float(sector_rotation.get("force_score") or rotation.get("force_score") or 0.0)
    return _force("sector_rotation", score, "ok" if rotation else "unavailable", rotation)


def risk_veto() -> dict[str, Any]:
    files = [
        VIBE_HOME / "PORTFOLIO_KILL_SWITCH.json",
        VIBE_HOME / "MANUAL_RESET_REQUIRED.json",
        VIBE_HOME / "KALSHI_MANUAL_RESET_REQUIRED.json",
    ]
    active = [str(path) for path in files if path.exists()]
    return {
        "active": bool(active),
        "files": active,
        "status": "blocked" if active else "clear",
    }


def classify_score(score: float, veto: dict[str, Any]) -> str:
    if veto.get("active"):
        return "risk_veto"
    if score >= 3:
        return "bullish_confirmation"
    if score <= -3:
        return "bearish_confirmation"
    if score >= 1:
        return "bullish_lean"
    if score <= -1:
        return "bearish_lean"
    return "mixed"


def build_score(day: str | None = None, paths: dict[str, Path] | None = None) -> dict[str, Any]:
    day = day or date.today().isoformat()
    paths = paths or SOURCE_PATHS
    rows = {name: latest_for_day(path, day) for name, path in paths.items()}
    trend = trend_force(rows["opening_range"])
    gex = gex_force(rows["gex"], float(trend["score"]))
    momentum = momentum_force(rows["ttm_squeeze"], rows["wavetrend"], rows["smc"])
    vix_context = None
    for row in (rows["ttm_squeeze"], rows["wavetrend"], rows["smc"]):
        if isinstance(row, dict) and isinstance(row.get("vix_context"), dict):
            vix_context = row["vix_context"]
            break
    volatility = volatility_force(rows["ivr"], vix_context)
    rv_iv = rv_iv_force(rows["rv_iv_regime"])
    hurst = hurst_force(rows["hurst_regime"])
    narrative = narrative_force(rows["preopen_sentiment"], rows["social_trending"], rows["relative_volume"])
    institutional = institutional_force(rows["distribution_days"])
    breadth = breadth_force(rows["market_breadth"])
    sector_rotation = sector_rotation_force(rows["sector_rotation"])
    forces = [trend, gex, momentum, volatility, rv_iv, hurst, narrative, institutional, breadth, sector_rotation]
    total = round(sum(float(force["score"]) for force in forces), 3)
    coverage = sum(1 for force in forces if force["status"] != "missing")
    veto = risk_veto()
    classification = classify_score(total, veto)
    confidence = min(10.0, round(abs(total) + coverage, 2))
    return {
        "date": day,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "market_force_score",
        "mode": "read_only",
        "execution_enabled": False,
        "classification": classification,
        "total_score": total,
        "confidence": confidence,
        "coverage": {"available_forces": coverage, "total_forces": len(forces)},
        "risk_veto": veto,
        "forces": forces,
        "source_paths": {name: str(path) for name, path in paths.items()},
        "warnings": [
            "Read-only score. No broker orders are wired.",
            "Do not use as an execution gate until forward-test outcomes prove value.",
            "Missing close-time momentum logs are expected before 15:20 local.",
        ],
    }


def append_log(entry: dict[str, Any], log_path: Path = LOG_PATH) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, separators=(",", ":")) + "\n")


def write_report(entry: dict[str, Any], report_path: Path = REPORT_PATH) -> Path:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(entry, indent=2), encoding="utf-8")
    return report_path


def print_report(entry: dict[str, Any]) -> None:
    print("\nMarket Force Score | read-only")
    print("=" * 76)
    print(
        f"{entry['date']} classification={entry['classification']} "
        f"score={entry['total_score']} confidence={entry['confidence']} "
        f"coverage={entry['coverage']['available_forces']}/{entry['coverage']['total_forces']}"
    )
    for force in entry["forces"]:
        print(f"{force['name']:<14} {force['direction']:<8} score={force['score']:<5} status={force['status']}")
    if entry["risk_veto"]["active"]:
        print(f"RISK VETO ACTIVE: {entry['risk_veto']['files']}")
    print("No orders placed.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build read-only daily Market Force Score.")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_output")
    args = parser.parse_args()
    entry = build_score(day=args.date)
    append_log(entry, args.log_path)
    write_report(entry, args.report_path)
    if args.print_output:
        print_report(entry)
    else:
        print(f"Market force score logged to {args.log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
