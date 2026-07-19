#!/usr/bin/env python3
"""Prop-firm rule gate for shadow/paper/live trading workflows.

This module is intentionally deterministic. It does not decide whether a setup
has edge; it decides whether a proposed trade is allowed under a verified
firm/account rule profile.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

Side = Literal["buy", "sell", "short", "cover", "close"]


@dataclass(frozen=True)
class ProposedTrade:
    symbol: str
    side: Side
    contracts: int
    risk_dollars: float
    automated: bool = True
    running_on_vps: bool = False
    would_be_best_day_profit: float = 0.0


@dataclass(frozen=True)
class AccountState:
    equity: float
    start_equity: float
    day_pnl: float
    trailing_drawdown_remaining: float
    current_contracts: int = 0
    total_profit: float = 0.0
    best_day_profit: float = 0.0


@dataclass(frozen=True)
class PropGateDecision:
    allowed: bool
    confidence_score: int
    reasons: list[str]
    firm: str
    account_type: str


REQUIRED_PROFILE_FIELDS = ("firm", "account_type", "automation", "risk", "unknown_rules_block")
REQUIRED_RISK_FIELDS = ("max_daily_loss", "max_trailing_drawdown", "max_contracts")


def load_rule_profile(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def profile_confidence_score(profile: dict[str, Any]) -> int:
    score = 0
    if all(field in profile for field in REQUIRED_PROFILE_FIELDS):
        score += 35
    automation = profile.get("automation") or {}
    if "allowed" in automation and "status" in automation:
        score += 20
    risk = profile.get("risk") or {}
    if all(field in risk for field in REQUIRED_RISK_FIELDS):
        score += 25
    if profile.get("unknown_rules_block") is True:
        score += 10
    if profile.get("verified_as_of") and profile.get("sources"):
        score += 10
    return min(score, 100)


def _missing_required(profile: dict[str, Any]) -> list[str]:
    missing = [field for field in REQUIRED_PROFILE_FIELDS if field not in profile]
    risk = profile.get("risk") or {}
    missing.extend(f"risk.{field}" for field in REQUIRED_RISK_FIELDS if field not in risk)
    automation = profile.get("automation") or {}
    for field in ("allowed", "status"):
        if field not in automation:
            missing.append(f"automation.{field}")
    return missing


def evaluate_prop_trade(
    profile: dict[str, Any],
    trade: ProposedTrade,
    account: AccountState,
) -> PropGateDecision:
    reasons: list[str] = []
    firm = str(profile.get("firm", "unknown"))
    account_type = str(profile.get("account_type", "unknown"))
    confidence = profile_confidence_score(profile)

    missing = _missing_required(profile)
    if missing and profile.get("unknown_rules_block", True):
        reasons.extend(f"missing_rule:{field}" for field in missing)

    automation = profile.get("automation") or {}
    if trade.automated and automation.get("allowed") is not True:
        reasons.append("automation_prohibited")
    if trade.automated and trade.running_on_vps and automation.get("requires_local_device"):
        reasons.append("vps_or_remote_server_prohibited")

    risk = profile.get("risk") or {}
    max_contracts = int(risk.get("max_contracts", 0) or 0)
    if max_contracts and account.current_contracts + trade.contracts > max_contracts:
        reasons.append("max_contracts")

    max_daily_loss = float(risk.get("max_daily_loss", 0) or 0)
    if max_daily_loss and account.day_pnl - trade.risk_dollars <= -max_daily_loss:
        reasons.append("daily_loss_limit")

    drawdown_remaining = float(account.trailing_drawdown_remaining)
    if drawdown_remaining and trade.risk_dollars >= drawdown_remaining:
        reasons.append("trailing_drawdown_limit")

    consistency = profile.get("consistency") or {}
    if consistency.get("enabled") and account.total_profit > 0:
        max_best_day_pct = float(consistency.get("max_best_day_pct", 0) or 0)
        projected_best_day = max(account.best_day_profit, trade.would_be_best_day_profit)
        projected_total = account.total_profit + max(0.0, trade.would_be_best_day_profit)
        if max_best_day_pct and projected_total > 0 and projected_best_day / projected_total > max_best_day_pct:
            reasons.append("consistency_rule")

    if not reasons:
        reasons.append("rules_passed")

    return PropGateDecision(
        allowed=reasons == ["rules_passed"],
        confidence_score=confidence,
        reasons=reasons,
        firm=firm,
        account_type=account_type,
    )
