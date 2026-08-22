"""Evidence gate for Robinhood Social options traders and shared trades."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class OptionsTraderProfile:
    handle: str
    source: str
    verified_by_robinhood: bool
    complete_closed_history: bool
    losing_trades_included: bool
    closed_trades: int
    distinct_trading_days: int
    profit_factor: float
    expectancy_per_trade: float
    max_drawdown_pct: float
    bounded_risk_trade_fraction: float
    median_signal_delay_seconds: float
    coverage_manifest_verified: bool = False
    trades_visible: bool = True
    exact_contracts_visible: bool = True


def evaluate_trader(profile: OptionsTraderProfile) -> dict[str, Any]:
    blockers = []
    supported_sources = {
        "kinfo_broker_verified_public",
        "robinhood_activity_export",
        "robinhood_social_verified",
    }
    if profile.source not in supported_sources:
        blockers.append("unsupported_or_unverified_source")
    if not profile.verified_by_robinhood:
        blockers.append("identity_or_trade_not_robinhood_verified")
    if not profile.complete_closed_history or not profile.losing_trades_included:
        blockers.append("incomplete_history_or_missing_losses")
    if profile.source == "kinfo_broker_verified_public":
        if not profile.coverage_manifest_verified:
            blockers.append("kinfo_account_coverage_not_verified")
        if not profile.trades_visible or not profile.exact_contracts_visible:
            blockers.append("kinfo_trades_hidden_or_not_replicable")
    if profile.closed_trades < 100:
        blockers.append("fewer_than_100_closed_trades")
    if profile.distinct_trading_days < 60:
        blockers.append("fewer_than_60_distinct_days")
    if profile.profit_factor < 1.30 or profile.expectancy_per_trade <= 0:
        blockers.append("positive_fee_adjusted_edge_not_proven")
    if profile.max_drawdown_pct > 0.15:
        blockers.append("drawdown_above_15_pct")
    if profile.bounded_risk_trade_fraction < 0.95:
        blockers.append("unbounded_risk_history")
    if profile.median_signal_delay_seconds > 300:
        blockers.append("signals_not_copyable_at_observed_latency")
    return {
        **asdict(profile),
        "status": "paper_watch" if not blockers else "reject",
        "blockers": blockers,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def evaluate_shared_trade(
    trade: dict[str, Any],
    profile_result: dict[str, Any],
    *,
    now: datetime,
    max_age_seconds: float = 300.0,
    max_price_drift: float = 0.05,
) -> dict[str, Any]:
    blockers = []
    if profile_result.get("status") != "paper_watch":
        blockers.append("trader_not_paper_watch")
    if not trade.get("robinhood_verified_trade"):
        blockers.append("trade_not_robinhood_verified")
    if not trade.get("defined_risk") or float(trade.get("max_loss_dollars") or 0.0) <= 0:
        blockers.append("missing_defined_max_loss")
    try:
        observed = datetime.fromisoformat(str(trade.get("observed_at") or "").replace("Z", "+00:00"))
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        age = (now.astimezone(timezone.utc) - observed.astimezone(timezone.utc)).total_seconds()
    except ValueError:
        age = float("inf")
    if age < -5 or age > max_age_seconds:
        blockers.append("stale_shared_trade")
    leader_price = float(trade.get("leader_executable_price") or 0.0)
    current_price = float(trade.get("current_executable_price") or 0.0)
    drift = abs(current_price - leader_price) / leader_price if leader_price > 0 and current_price > 0 else 1.0
    if drift > max_price_drift:
        blockers.append("price_drift_above_5_pct")
    return {
        "trader": profile_result.get("handle"),
        "trade_id": trade.get("trade_id"),
        "strategy": trade.get("strategy"),
        "action": "paper_candidate" if not blockers else "skip",
        "blockers": blockers,
        "age_seconds": round(age, 3) if age != float("inf") else None,
        "price_drift": round(drift, 4),
        "execution_enabled": False,
        "can_submit_orders": False,
        "knowledge_use": "extract_and_test_rules_not_blind_mirroring",
    }
