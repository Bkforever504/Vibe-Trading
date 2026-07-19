"""Fail-closed readiness checks for future Flip Bot live entries."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


LIVE_APPROVAL_ACK = "I_UNDERSTAND_LIVE_CAPITAL_IS_AT_RISK"


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


@dataclass(frozen=True)
class LiveReadiness:
    ready: bool
    blockers: tuple[str, ...]
    details: dict[str, Any]


def evaluate_live_readiness(
    account: dict[str, Any] | None,
    *,
    live_enabled: bool,
    approval_ack: str,
) -> LiveReadiness:
    """Evaluate broker/account prerequisites without changing broker state."""
    account = account or {}
    blockers: list[str] = []
    if not live_enabled:
        blockers.append("live_execution_not_enabled")
    if approval_ack != LIVE_APPROVAL_ACK:
        blockers.append("explicit_live_capital_ack_missing")
    if not account:
        blockers.append("live_account_unavailable")

    status = str(account.get("status") or "").upper()
    if account and status != "ACTIVE":
        blockers.append("live_account_not_active")
    if bool(account.get("account_blocked")):
        blockers.append("broker_account_blocked")
    if bool(account.get("trading_blocked")):
        blockers.append("broker_trading_blocked")
    if bool(account.get("trade_suspended_by_user")):
        blockers.append("broker_trading_suspended_by_user")

    options_level = max(
        _int(account.get("options_trading_level")),
        _int(account.get("options_approved_level")),
    )
    if account and options_level < 2:
        blockers.append("long_options_level_2_not_approved")

    equity = _float(account.get("equity"))
    buying_power = _float(account.get("options_buying_power") or account.get("buying_power"))
    if account and equity <= 0:
        blockers.append("live_equity_unavailable")
    if account and buying_power <= 0:
        blockers.append("live_options_buying_power_unavailable")

    details = {
        "status": status or None,
        "equity": equity,
        "options_buying_power": buying_power,
        "options_trading_level": options_level,
        "account_blocked": bool(account.get("account_blocked")),
        "trading_blocked": bool(account.get("trading_blocked")),
        "trade_suspended_by_user": bool(account.get("trade_suspended_by_user")),
        "approval_ack_present": approval_ack == LIVE_APPROVAL_ACK,
        "live_enabled": bool(live_enabled),
    }
    return LiveReadiness(not blockers, tuple(blockers), details)


def affordable_contracts(
    *,
    account_equity: float,
    option_price: float,
    max_notional_pct: float,
    max_contracts: int,
) -> dict[str, Any]:
    """Mirror the bot's premium-notional sizing exactly."""
    budget = max(0.0, float(account_equity) * float(max_notional_pct))
    contract_cost = max(0.0, float(option_price) * 100.0)
    raw = int(budget // contract_cost) if contract_cost > 0 else 0
    contracts = min(raw, max(0, int(max_contracts)))
    return {
        "account_equity": round(float(account_equity), 2),
        "option_price": round(float(option_price), 4),
        "max_notional_pct": float(max_notional_pct),
        "premium_budget": round(budget, 2),
        "contract_cost": round(contract_cost, 2),
        "contracts": contracts,
        "affordable": contracts >= 1,
    }
