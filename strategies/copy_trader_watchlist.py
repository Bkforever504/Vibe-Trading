#!/usr/bin/env python3
"""Paper-only copy-trader watchlist and risk scoring.

This module evaluates public or manually exported trader histories. It does
not submit trades, store private keys, or automate any third-party platform.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RUNTIME_DIR = Path(os.path.expanduser(r"~\.vibe-trading"))
REPORT_DIR = RUNTIME_DIR / "reports"
REPORT_FILE = REPORT_DIR / "copy-trader-watchlist.json"
DEFAULT_PROFILES_FILE = RUNTIME_DIR / "copy-trader-profiles.json"
DEFAULT_SIGNALS_FILE = RUNTIME_DIR / "copy-trader-signals.json"
DEFAULT_COPY_RISK_PCT = 0.01
MAX_PRICE_DRIFT = 0.05


@dataclass(frozen=True)
class TraderProfile:
    handle: str
    platform: str
    source: str
    trades: int
    win_rate: float
    realized_pnl: float
    max_drawdown_pct: float
    avg_leverage: float = 1.0
    profit_factor: float = 0.0
    verified: bool = False
    category: str = "general"
    pnl_smoothness: float = 0.0
    green_months: int = 0
    monthly_consistency: float = 0.0
    worst_month_pct: float = 0.0
    avg_edge_per_trade: float = 0.0
    fee_adjusted_return: float = 0.0
    trade_frequency: str = "unknown"


@dataclass(frozen=True)
class ScoredTrader:
    handle: str
    platform: str
    source: str
    trades: int
    win_rate: float
    realized_pnl: float
    max_drawdown_pct: float
    avg_leverage: float
    profit_factor: float
    verified: bool
    category: str
    confidence: int
    status: str
    risk_flags: list[str]
    reason: str
    conviction_score: int
    suggested_copy_size: float


@dataclass(frozen=True)
class CopySignal:
    trader: str
    platform: str
    symbol: str
    side: str
    leader_price: float
    current_price: float
    leader_notional: float
    observed_at: str
    category: str = "general"


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: object, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def profile_from_dict(data: dict[str, Any]) -> TraderProfile:
    return TraderProfile(
        handle=str(data.get("handle") or data.get("wallet") or ""),
        platform=str(data.get("platform") or "unknown"),
        source=str(data.get("source") or "manual"),
        trades=_safe_int(data.get("trades")),
        win_rate=_safe_float(data.get("win_rate")),
        realized_pnl=_safe_float(data.get("realized_pnl") or data.get("pnl")),
        max_drawdown_pct=_safe_float(data.get("max_drawdown_pct") or data.get("drawdown")),
        avg_leverage=_safe_float(data.get("avg_leverage"), 1.0),
        profit_factor=_safe_float(data.get("profit_factor")),
        verified=bool(data.get("verified")),
        category=str(data.get("category") or "general"),
        pnl_smoothness=_safe_float(data.get("pnl_smoothness")),
        green_months=_safe_int(data.get("green_months")),
        monthly_consistency=_safe_float(data.get("monthly_consistency")),
        worst_month_pct=_safe_float(data.get("worst_month_pct")),
        avg_edge_per_trade=_safe_float(data.get("avg_edge_per_trade")),
        fee_adjusted_return=_safe_float(data.get("fee_adjusted_return")),
        trade_frequency=str(data.get("trade_frequency") or "unknown"),
    )


def signal_from_dict(data: dict[str, Any]) -> CopySignal:
    return CopySignal(
        trader=str(data.get("trader") or data.get("handle") or ""),
        platform=str(data.get("platform") or "unknown"),
        symbol=str(data.get("symbol") or data.get("market") or ""),
        side=str(data.get("side") or data.get("outcome") or "").upper(),
        leader_price=_safe_float(data.get("leader_price") or data.get("entry_price")),
        current_price=_safe_float(data.get("current_price") or data.get("mark_price")),
        leader_notional=_safe_float(data.get("leader_notional") or data.get("notional")),
        observed_at=str(data.get("observed_at") or data.get("created_at") or ""),
        category=str(data.get("category") or "general"),
    )


def load_profiles(path: Path = DEFAULT_PROFILES_FILE) -> list[TraderProfile]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        return []
    return [profile_from_dict(item) for item in data if isinstance(item, dict)]


def load_signals(path: Path = DEFAULT_SIGNALS_FILE) -> list[CopySignal]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        return []
    return [signal_from_dict(item) for item in data if isinstance(item, dict)]


def score_trader(profile: TraderProfile) -> ScoredTrader:
    score = 0
    reasons: list[str] = []
    flags: list[str] = []

    if profile.source == "public_leaderboard":
        flags.append("missing exported trade history")
        if profile.win_rate <= 0:
            flags.append("public leaderboard lacks win rate")
    if (
        profile.source == "public_wallet"
        and profile.trades >= 100
        and profile.win_rate <= 0
        and profile.realized_pnl == 0
        and profile.profit_factor <= 0
    ):
        flags.append("unmeasurable pnl history")

    if profile.verified:
        score += 2
        reasons.append("verified history")
    else:
        flags.append("unverified social data")

    if profile.trades >= 100:
        score += 2
        reasons.append("100+ trade sample")
    elif profile.trades >= 30:
        score += 1
        reasons.append("minimum sample")
    else:
        flags.append("sample too small")

    if profile.win_rate >= 0.55:
        score += 1
    if profile.profit_factor >= 1.5:
        score += 2
        reasons.append("profit factor above 1.5")
    elif profile.profit_factor >= 1.2:
        score += 1

    if profile.realized_pnl > 0:
        score += 1
    if profile.max_drawdown_pct <= 0.15:
        score += 1
        reasons.append("drawdown controlled")
    elif profile.max_drawdown_pct >= 0.30:
        flags.append("large drawdown")

    if profile.avg_leverage <= 3:
        score += 1
    elif profile.avg_leverage >= 10:
        flags.append("high leverage")

    if profile.source in {"public_wallet", "exported_history", "public_profile"}:
        score += 1
        if profile.source == "public_wallet":
            reasons.append("public wallet history")
        elif profile.source == "public_profile":
            reasons.append("public profile history")
        else:
            reasons.append("exported history")

    diligence_score = 0
    if profile.pnl_smoothness >= 0.70:
        diligence_score += 1
        reasons.append("smooth pnl curve")
    elif profile.pnl_smoothness and profile.pnl_smoothness < 0.35:
        flags.append("choppy pnl curve")

    if profile.green_months >= 5:
        diligence_score += 1
        reasons.append("all tracked months green")
    elif profile.green_months and profile.green_months < 3:
        flags.append("too few green months")

    if profile.monthly_consistency >= 0.65:
        diligence_score += 1
        reasons.append("consistent month-to-month pnl")
    elif profile.monthly_consistency and profile.monthly_consistency < 0.35:
        flags.append("weak month-to-month consistency")

    if profile.worst_month_pct >= -0.10:
        diligence_score += 1
    elif profile.worst_month_pct <= -0.20:
        flags.append("large losing month")

    if profile.avg_edge_per_trade >= 0.02 and profile.fee_adjusted_return >= 0.08:
        diligence_score += 1
        reasons.append("viable edge after fees")
    elif profile.avg_edge_per_trade or profile.fee_adjusted_return:
        if profile.avg_edge_per_trade < 0.01 or profile.fee_adjusted_return < 0.04:
            flags.append("edge too small after fees")

    if profile.trade_frequency in {"selective", "moderate"}:
        diligence_score += 1
        reasons.append("copyable trade cadence")
    elif profile.trade_frequency in {"hyperactive", "high_frequency"}:
        flags.append("overtrading risk")

    score += min(diligence_score, 2)

    if flags:
        score = max(0, score - len(flags))

    if "unmeasurable pnl history" in flags:
        status = "reject"
    else:
        status = "paper_watch" if score >= 7 and not flags else "review" if score >= 5 else "reject"
    confidence = min(score, 10)
    conviction_score = min(max(score + min(diligence_score, 3), 0), 10)
    suggested_copy_size = 0.0
    if status == "paper_watch":
        suggested_copy_size = 15.0 if conviction_score >= 8 and profile.trade_frequency == "selective" else 5.0
    return ScoredTrader(
        handle=profile.handle,
        platform=profile.platform,
        source=profile.source,
        trades=profile.trades,
        win_rate=profile.win_rate,
        realized_pnl=profile.realized_pnl,
        max_drawdown_pct=profile.max_drawdown_pct,
        avg_leverage=profile.avg_leverage,
        profit_factor=profile.profit_factor,
        verified=profile.verified,
        category=profile.category,
        confidence=confidence,
        status=status,
        risk_flags=flags,
        reason=", ".join(reasons) if reasons else "insufficient verified edge",
        conviction_score=conviction_score,
        suggested_copy_size=suggested_copy_size,
    )


def kelly_fraction(profile: TraderProfile) -> float:
    win_rate = max(0.0, min(profile.win_rate, 1.0))
    if profile.profit_factor <= 0 or win_rate <= 0:
        return 0.0
    fraction = win_rate - ((1.0 - win_rate) / profile.profit_factor)
    return round(max(0.0, min(fraction, 1.0)), 4)


def _rejection_guidance(flags: list[str]) -> list[str]:
    guidance_map = {
        "sample too small": "Need: 30+ trades minimum, 100+ preferred",
        "choppy pnl curve": "Need: pnl_smoothness >= 0.70 (linear equity growth)",
        "unverified social data": "Need: exported broker history or verified public wallet",
        "large drawdown": "Need: max drawdown under 15%, never over 30%",
        "high leverage": "Need: low/no leverage history before copy consideration",
        "too few green months": "Need: 5+ green months or at least 65% positive months",
        "weak month-to-month consistency": "Need: monthly_consistency >= 0.65",
        "large losing month": "Need: no month worse than -10% of tracked notional",
        "edge too small after fees": "Need: avg_edge_per_trade >= 0.02 and fee_adjusted_return >= 0.08",
        "overtrading risk": "Need: selective or moderate trade cadence",
        "missing exported trade history": "Need: exported fills/history before paper-copy approval",
        "public leaderboard lacks win rate": "Need: measurable win rate from exported fills or public trade history",
        "unmeasurable pnl history": "Need: realized P&L, win rate, and profit factor before copy consideration",
    }
    return [guidance_map.get(flag, f"Review required: {flag}") for flag in flags]


def build_basket_consensus(
    signals: list[CopySignal],
    profiles: list[TraderProfile],
    *,
    min_consensus: float = 0.80,
    min_traders: int = 3,
    account_size: float = 5_000.0,
) -> list[dict[str, Any]]:
    """Return markets where ≥80% of paper_watch traders agree on the same side.

    Requires min_traders active paper_watch traders for the ratio to be meaningful.
    Suggested notional uses avg Kelly × 15% of account, capped at 2%.
    """
    from collections import defaultdict
    scored_by_key = {(p.platform, p.handle): score_trader(p) for p in profiles}
    active = [p for p in profiles if scored_by_key[(p.platform, p.handle)].status == "paper_watch"]
    if len(active) < min_traders:
        return []

    profile_by_key = {(p.platform, p.handle): p for p in profiles}
    groups: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for sig in signals:
        key = (sig.platform, sig.trader)
        if key not in scored_by_key or scored_by_key[key].status != "paper_watch":
            continue
        groups[(sig.symbol, sig.side)].append(key)

    consensus: list[dict[str, Any]] = []
    for (symbol, side), trader_keys in groups.items():
        ratio = len(trader_keys) / len(active)
        if ratio >= min_consensus and len(trader_keys) >= min_traders:
            kellyvals = [
                kelly_fraction(profile_by_key[k])
                for k in trader_keys
                if k in profile_by_key
            ]
            avg_kelly = sum(kellyvals) / len(kellyvals) if kellyvals else 0.0
            consensus.append({
                "symbol": symbol,
                "side": side,
                "consensus_ratio": round(ratio, 3),
                "trader_count": len(trader_keys),
                "avg_kelly": round(avg_kelly, 4),
                "suggested_notional": round(account_size * min(avg_kelly * 0.15, 0.02), 2),
                "traders": [k[1] for k in trader_keys],
            })
    return sorted(consensus, key=lambda x: x["consensus_ratio"], reverse=True)


def simulate_copy_signal(
    signal: CopySignal,
    profile: TraderProfile,
    *,
    account_size: float = 5_000.0,
    risk_pct: float = DEFAULT_COPY_RISK_PCT,
    max_price_drift: float = MAX_PRICE_DRIFT,
) -> dict[str, Any]:
    scored = score_trader(profile)
    leader_price = max(signal.leader_price, 0.0)
    current_price = max(signal.current_price, 0.0)
    drift = abs(current_price - leader_price) / leader_price if leader_price else 1.0
    stale = drift > max_price_drift
    approved = scored.status == "paper_watch" and not stale
    kelly = kelly_fraction(profile)
    sized_risk_pct = min(risk_pct, kelly * 0.5) if approved else 0.0
    notional = round(max(0.0, account_size * sized_risk_pct), 2) if approved else 0.0
    return {
        "trader": signal.trader,
        "platform": signal.platform,
        "symbol": signal.symbol,
        "side": signal.side,
        "category": signal.category,
        "observed_at": signal.observed_at,
        "leader_price": round(leader_price, 6),
        "current_price": round(current_price, 6),
        "price_drift": round(drift, 4),
        "stale_price": stale,
        "confidence": scored.confidence,
        "action": "paper_copy" if approved else "skip",
        "notional": notional,
        "risk_pct": round(sized_risk_pct, 4),
        "kelly_fraction": kelly,
        "reason": "paper-copy simulated" if approved else "stale price or trader not approved",
    }


def build_report(
    profiles: list[TraderProfile],
    *,
    signals: list[CopySignal] | None = None,
    account_size: float = 5_000.0,
) -> dict[str, Any]:
    scored = [score_trader(profile) for profile in profiles if profile.handle]
    scored.sort(key=lambda item: (item.confidence, item.realized_pnl, item.trades), reverse=True)
    rejected = [
        {
            "handle": item.handle,
            "platform": item.platform,
            "confidence": item.confidence,
            "status": item.status,
            "risk_flags": item.risk_flags,
            "what_would_help": _rejection_guidance(item.risk_flags),
        }
        for item in scored
        if item.status == "reject"
    ]
    profile_by_key = {(profile.platform, profile.handle): profile for profile in profiles}
    paper_signals = []
    for signal in signals or []:
        profile = profile_by_key.get((signal.platform, signal.trader))
        if profile:
            paper_signals.append(simulate_copy_signal(signal, profile, account_size=account_size))
    basket = build_basket_consensus(signals or [], profiles, account_size=account_size)
    return {
        "provider": "copy_trader_watchlist",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "paper_only",
        "execution_enabled": False,
        "watched_count": len(scored),
        "watched_traders": [asdict(item) for item in scored],
        "rejected_count": len(rejected),
        "rejected_traders": rejected,
        "paper_signal_count": len(paper_signals),
        "paper_signals": paper_signals,
        "basket_consensus_count": len(basket),
        "basket_consensus": basket,
        "warnings": [
            "Paper-only: no copy-trading execution is implemented.",
            "Use verified public wallet or exported broker history before trusting any social leaderboard.",
            "Basket consensus requires ≥80% of paper_watch traders agreeing on same market+side.",
        ],
    }


def write_report(report: dict[str, Any], path: Path = REPORT_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")


def run_report(
    *,
    profiles_path: Path = DEFAULT_PROFILES_FILE,
    signals_path: Path = DEFAULT_SIGNALS_FILE,
    out: Path = REPORT_FILE,
) -> dict[str, Any]:
    report = build_report(load_profiles(profiles_path), signals=load_signals(signals_path))
    write_report(report, out)
    return report
