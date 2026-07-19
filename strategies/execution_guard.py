#!/usr/bin/env python3
"""Shared hard gates for automated order execution.

This module is intentionally broker-agnostic. Strategy code should ask it for a
decision before submitting any opening order, then log/alert the exact reason if
the order is blocked.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from strategies.portfolio_guard import PORTFOLIO_KILL_FILE, portfolio_kill_active
from strategies.risk_kill_switch import DEFAULT_BLOCK_FILE, write_block_file

GUARD_BLOCK_LOG_FILE = Path(os.path.expanduser(r"~\.vibe-trading\guard-blocks.jsonl"))


@dataclass(frozen=True)
class ExecutionGuardConfig:
    min_confidence: float = 8.5
    max_daily_loss_pct: float = 0.03
    max_spread_cents: int | None = None


@dataclass(frozen=True)
class ExecutionDecision:
    allowed: bool
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _append_block_log(decision: "ExecutionDecision") -> None:
    try:
        GUARD_BLOCK_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with GUARD_BLOCK_LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {"allowed": decision.allowed, "reason": decision.reason, "details": decision.details},
                    sort_keys=True,
                )
                + "\n"
            )
    except Exception:
        pass


def _block_details(
    *,
    bot: str,
    symbol: str,
    action: str,
    paper: bool,
    live_enabled: bool,
    confidence: float | None,
    estimated_notional: float,
    max_notional: float,
    contracts: int,
    max_contracts: int,
    spread_cents: int | None,
    daily_loss_pct: float,
    open_symbols: set[str],
    config: ExecutionGuardConfig,
) -> dict[str, Any]:
    return {
        "bot": bot,
        "symbol": symbol,
        "action": action,
        "paper": paper,
        "live_enabled": live_enabled,
        "confidence": confidence,
        "min_confidence": config.min_confidence,
        "estimated_notional": estimated_notional,
        "max_notional": max_notional,
        "contracts": contracts,
        "max_contracts": max_contracts,
        "spread_cents": spread_cents,
        "max_spread_cents": config.max_spread_cents,
        "daily_loss_pct": daily_loss_pct,
        "max_daily_loss_pct": config.max_daily_loss_pct,
        "open_symbols": sorted(open_symbols),
        "checked_at": _utc_now(),
    }


def evaluate_execution(
    *,
    bot: str,
    symbol: str,
    action: str,
    paper: bool,
    live_enabled: bool,
    confidence: float | None,
    estimated_notional: float,
    max_notional: float,
    contracts: int,
    max_contracts: int,
    block_file: Path = DEFAULT_BLOCK_FILE,
    spread_cents: int | None = None,
    daily_loss_pct: float = 0.0,
    open_symbols: set[str] | None = None,
    config: ExecutionGuardConfig = ExecutionGuardConfig(),
) -> ExecutionDecision:
    """Return whether an automated order is allowed by hard risk controls."""
    normalized_open_symbols = {str(s).upper() for s in (open_symbols or set()) if s}
    details = _block_details(
        bot=bot,
        symbol=symbol,
        action=action,
        paper=paper,
        live_enabled=live_enabled,
        confidence=confidence,
        estimated_notional=estimated_notional,
        max_notional=max_notional,
        contracts=contracts,
        max_contracts=max_contracts,
        spread_cents=spread_cents,
        daily_loss_pct=daily_loss_pct,
        open_symbols=normalized_open_symbols,
        config=config,
    )

    def _blocked(reason: str, d: dict) -> ExecutionDecision:
        dec = ExecutionDecision(False, reason, d)
        _append_block_log(dec)
        return dec

    if portfolio_kill_active():
        return _blocked("portfolio_kill_switch", {**details, "kill_file": str(PORTFOLIO_KILL_FILE)})

    if block_file.exists():
        return _blocked("manual_reset_required", {**details, "block_file": str(block_file)})

    if not paper and not live_enabled:
        return _blocked("live_execution_not_enabled", details)

    if confidence is None or confidence < config.min_confidence:
        return _blocked("confidence_below_minimum", details)

    if contracts < 1:
        return _blocked("invalid_contract_count", details)

    if contracts > max_contracts:
        return _blocked("contracts_above_limit", details)

    if max_notional > 0 and estimated_notional > max_notional:
        return _blocked("notional_above_limit", details)

    if config.max_spread_cents is not None and spread_cents is not None and spread_cents > config.max_spread_cents:
        return _blocked("spread_too_wide", details)

    if str(symbol).upper() in normalized_open_symbols:
        return _blocked("duplicate_symbol_exposure", details)

    if config.max_spread_cents is not None and spread_cents is None:
        return _blocked("spread_quote_unavailable", details)

    if daily_loss_pct >= config.max_daily_loss_pct:
        write_block_file(
            block_file,
            reason="daily_loss_limit",
            source=f"{bot}_execution_guard",
            details=details,
        )
        return _blocked("daily_loss_limit", details)

    return ExecutionDecision(True, "allowed", details)


def decision_to_json(decision: ExecutionDecision) -> str:
    return json.dumps(
        {
            "allowed": decision.allowed,
            "reason": decision.reason,
            "details": decision.details,
        },
        sort_keys=True,
    )
