#!/usr/bin/env python3
"""Deterministic options position/state reconciliation and durable-state safety.

Shared by strategies/iwm_options_bot.py and scripts/options_position_reconciler.py.

Design rules:
- Pure stdlib. Never imports broker SDKs. Never submits orders.
- Quantity-aware and direction-aware: two groups holding opposite sides of the
  same OCC contract net to zero at the broker. Symbol-set comparisons cannot
  see this; signed-quantity books can.
- Fail closed: any unexplained discrepancy blocks new entries.
- Read-only analytics: reconcile() never mutates the trade state it is given.

Group state machine (GROUP_STATES):
    tracked -> partially_filled -> open -> exit_pending -> closing
    -> partially_closed -> flat_pending_confirmation -> closed
    any -> manual_review (terminal until a human clears it)
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

OCC_RE = re.compile(r"^([A-Z]+)(\d{6})([CP])(\d{8})$")

GROUP_STATES = (
    "tracked",
    "partially_filled",
    "open",
    "exit_pending",
    "closing",
    "partially_closed",
    "flat_pending_confirmation",
    "closed",
    "manual_review",
)

ACTIVE_STATUSES = {"open", "closing"}

# Statuses that may legitimately still have broker legs.
BROKER_PRESENT_OK = {
    "open", "closing", "exit_pending", "partially_filled",
    "partially_closed", "flat_pending_confirmation", "tracked",
}


# ── OCC helpers ────────────────────────────────────────────────────────────────
def occ_underlying(symbol: str) -> str:
    match = OCC_RE.match(str(symbol))
    return match.group(1) if match else str(symbol)


def occ_parts(symbol: str) -> Optional[dict]:
    match = OCC_RE.match(str(symbol))
    if not match:
        return None
    return {
        "underlying": match.group(1),
        "expiry": match.group(2),
        "right": match.group(3),
        "strike": int(match.group(4)) / 1000.0,
    }


# ── Leg detail inference ───────────────────────────────────────────────────────
def infer_leg_details(trade: dict) -> list[dict]:
    """Return per-leg [{symbol, side, qty, inferred}] with signed intent.

    Prefers explicit trade["leg_details"] recorded at submission time.
    Falls back to structural inference for known credit strategies and marks
    those legs inferred=True so downstream consumers can weight confidence.
    """
    qty = int(trade.get("qty") or 1)
    explicit = trade.get("leg_details")
    if isinstance(explicit, list) and explicit:
        details = []
        for leg in explicit:
            if not isinstance(leg, dict) or not leg.get("symbol"):
                continue
            ratio = int(leg.get("ratio_qty") or 1)
            details.append({
                "symbol": str(leg["symbol"]),
                "side": "sell" if str(leg.get("side", "")).lower() == "sell" else "buy",
                "qty": qty * ratio,
                "inferred": False,
            })
        if details:
            return details

    legs = [str(s) for s in (trade.get("legs") or [])]
    strategy = str(trade.get("strategy") or "")
    sides = _infer_sides(legs, strategy)
    return [
        {"symbol": symbol, "side": side, "qty": qty, "inferred": True}
        for symbol, side in zip(legs, sides)
    ]


def _infer_sides(legs: list[str], strategy: str) -> list[str]:
    """Infer sell/buy per leg for credit structures.

    Convention in this repo: iron_condor legs are recorded
    [short_put, long_put, short_call, long_call]; put_spread legs are
    [short_put, long_put]. For recovered/unknown groups, use strike ordering:
    among puts the higher strike is short; among calls the lower strike is
    short (credit-structure assumption).
    """
    if strategy == "iron_condor" and len(legs) == 4:
        return ["sell", "buy", "sell", "buy"]
    if strategy == "put_spread" and len(legs) == 2:
        return ["sell", "buy"]

    parsed = [(symbol, occ_parts(symbol)) for symbol in legs]
    sides: dict[str, str] = {}
    for right in ("P", "C"):
        group = [(s, p) for s, p in parsed if p and p["right"] == right]
        if len(group) == 2:
            ordered = sorted(group, key=lambda item: item[1]["strike"], reverse=(right == "P"))
            sides[ordered[0][0]] = "sell"
            sides[ordered[1][0]] = "buy"
        else:
            for s, _ in group:
                sides[s] = "sell"  # conservative: assume exposure
    return [sides.get(symbol, "sell") for symbol in legs]


def signed_book(trades: Iterable[dict]) -> dict[str, int]:
    """Per-OCC-symbol signed contract quantity expected from these trades."""
    book: dict[str, int] = {}
    for trade in trades:
        for leg in infer_leg_details(trade):
            signed = leg["qty"] if leg["side"] == "buy" else -leg["qty"]
            book[leg["symbol"]] = book.get(leg["symbol"], 0) + signed
    return {symbol: qty for symbol, qty in book.items()}


def quote_mark(trade: dict, quotes: dict[str, dict]) -> dict:
    """Mark an economic option group from per-leg bid/ask quotes.

    The broker may omit a contract whose opposite sides net to zero across
    groups. Group P&L therefore cannot depend on the broker position list.
    Midpoint is used for monitoring; the natural liquidation value (buy short
    legs at ask, sell long legs at bid) is used as the close-order limit.
    """
    details = infer_leg_details(trade)
    group_qty = max(1, int(trade.get("qty") or 1))
    if not details:
        return {"status": "unavailable", "reason": "no_leg_details", "missing_quotes": []}

    midpoint_debit = 0.0
    natural_debit = 0.0
    widest_spread_pct = 0.0
    missing: list[str] = []
    legs: list[dict] = []
    inferred = False

    for detail in details:
        symbol = str(detail["symbol"])
        quote = quotes.get(symbol)
        if not isinstance(quote, dict):
            missing.append(symbol)
            continue
        try:
            bid = float(quote.get("bid") or 0.0)
            ask = float(quote.get("ask") or 0.0)
        except (TypeError, ValueError):
            missing.append(symbol)
            continue
        if bid < 0 or ask <= 0 or ask < bid:
            missing.append(symbol)
            continue

        mid = (bid + ask) / 2.0
        spread_pct = (ask - bid) / mid if mid > 0 else float("inf")
        widest_spread_pct = max(widest_spread_pct, spread_pct)
        ratio = max(1.0, float(detail.get("qty") or group_qty) / group_qty)
        side = str(detail.get("side") or "buy")
        inferred = inferred or bool(detail.get("inferred"))
        if side == "sell":
            midpoint_debit += mid * ratio
            natural_debit += ask * ratio
            close_side = "buy"
        else:
            midpoint_debit -= mid * ratio
            natural_debit -= bid * ratio
            close_side = "sell"
        legs.append({
            "symbol": symbol,
            "entry_side": side,
            "close_side": close_side,
            "ratio_qty": int(ratio),
            "bid": round(bid, 4),
            "ask": round(ask, 4),
            "mid": round(mid, 4),
        })

    if missing:
        return {
            "status": "unavailable",
            "reason": "incomplete_leg_quotes",
            "missing_quotes": sorted(set(missing)),
            "quoted_leg_count": len(legs),
            "expected_leg_count": len(details),
        }

    midpoint_debit = max(0.0, midpoint_debit)
    natural_debit = max(0.0, natural_debit)
    net_credit = float(trade.get("net_credit") or 0.0)
    credit_dollars = net_credit * group_qty * 100
    pnl_dollars = (net_credit - midpoint_debit) * group_qty * 100
    pnl_pct = pnl_dollars / credit_dollars if credit_dollars > 0 else None
    return {
        "status": "ok",
        "source": "all_leg_latest_quotes",
        "marked_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "midpoint_close_debit": round(midpoint_debit, 4),
        "natural_close_debit": round(natural_debit, 4),
        "net_credit": round(net_credit, 4),
        "pnl_dollars": round(pnl_dollars, 2),
        "pnl_pct_of_credit": round(pnl_pct, 6) if pnl_pct is not None else None,
        "widest_spread_pct": round(widest_spread_pct, 4),
        "leg_details_inferred": inferred,
        "missing_quotes": [],
        "legs": legs,
    }


# ── Reconciliation ─────────────────────────────────────────────────────────────
def close_transition_plan(
    trade: dict,
    active_trades: list[dict],
    broker_positions: list[dict],
) -> dict:
    """Prove and describe an atomic group close against the signed broker book.

    A leg shared by opposite-side groups can be absent from the broker because
    its net quantity is zero. Closing one group must then open the surviving
    group's side of that contract while closing the target group's other legs.
    Any unexplained mismatch or quantity crossing makes the plan unavailable.
    """
    trade_id = str(trade.get("id") or trade.get("label") or "?")
    active = [t for t in active_trades if t.get("status") in ACTIVE_STATUSES]
    matches = [
        t for t in active
        if str(t.get("id") or t.get("label") or "?") == trade_id
    ]
    if len(matches) != 1:
        return {
            "status": "unavailable",
            "reason": "target_group_not_uniquely_active",
            "trade_id": trade_id,
        }

    expected = {symbol: qty for symbol, qty in signed_book(active).items() if qty}
    tracked_symbols = {
        str(leg) for active_trade in active for leg in (active_trade.get("legs") or [])
    }
    broker: dict[str, int] = {}
    for position in broker_positions:
        if not isinstance(position, dict):
            continue
        symbol = str(position.get("symbol") or "")
        if symbol not in tracked_symbols:
            continue
        try:
            qty = int(round(float(position.get("qty") or 0)))
        except (TypeError, ValueError):
            return {
                "status": "unavailable",
                "reason": "invalid_broker_quantity",
                "trade_id": trade_id,
                "symbol": symbol,
            }
        if qty:
            broker[symbol] = broker.get(symbol, 0) + qty

    if broker != expected:
        all_symbols = sorted(set(broker) | set(expected))
        residual = {
            symbol: broker.get(symbol, 0) - expected.get(symbol, 0)
            for symbol in all_symbols
            if broker.get(symbol, 0) != expected.get(symbol, 0)
        }
        return {
            "status": "unavailable",
            "reason": "signed_book_mismatch",
            "trade_id": trade_id,
            "residual": residual,
        }

    group_book = {symbol: qty for symbol, qty in signed_book([trade]).items() if qty}
    details = infer_leg_details(trade)
    group_qty = max(1, int(trade.get("qty") or 1))
    if not group_book or len(details) != len(trade.get("legs") or []):
        return {
            "status": "unavailable",
            "reason": "incomplete_group_book",
            "trade_id": trade_id,
        }

    expected_after = dict(expected)
    for symbol, group_signed_qty in group_book.items():
        remaining = expected_after.get(symbol, 0) - group_signed_qty
        if remaining:
            expected_after[symbol] = remaining
        else:
            expected_after.pop(symbol, None)

    legs: list[dict] = []
    transition_legs: list[str] = []
    for detail in details:
        symbol = str(detail["symbol"])
        group_signed_qty = group_book.get(symbol, 0)
        if not group_signed_qty:
            return {
                "status": "unavailable",
                "reason": "ambiguous_group_leg",
                "trade_id": trade_id,
                "symbol": symbol,
            }
        order_signed_qty = -group_signed_qty
        broker_before = broker.get(symbol, 0)
        broker_after = broker_before + order_signed_qty
        if broker_after != expected_after.get(symbol, 0):
            return {
                "status": "unavailable",
                "reason": "post_close_book_mismatch",
                "trade_id": trade_id,
                "symbol": symbol,
            }

        side = "buy" if order_signed_qty > 0 else "sell"
        if broker_before == 0 or broker_before * order_signed_qty > 0:
            effect = "open"
            transition_legs.append(symbol)
        elif broker_before * group_signed_qty > 0 and abs(broker_before) >= abs(group_signed_qty):
            effect = "close"
        else:
            return {
                "status": "unavailable",
                "reason": "position_effect_crosses_zero",
                "trade_id": trade_id,
                "symbol": symbol,
                "broker_before": broker_before,
                "order_signed_qty": order_signed_qty,
            }

        leg_qty = int(detail.get("qty") or 0)
        if leg_qty <= 0 or leg_qty % group_qty:
            return {
                "status": "unavailable",
                "reason": "invalid_leg_ratio",
                "trade_id": trade_id,
                "symbol": symbol,
            }
        legs.append({
            "symbol": symbol,
            "side": side,
            "ratio_qty": str(leg_qty // group_qty),
            "position_intent": f"{side}_to_{effect}",
            "broker_qty_before": broker_before,
            "broker_qty_after": broker_after,
        })

    return {
        "status": "ok",
        "proof": "exact_signed_book_transition",
        "trade_id": trade_id,
        "planned_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "transition_legs": sorted(transition_legs),
        "expected_book_before": expected,
        "expected_book_after": expected_after,
        "legs": legs,
    }


def _classify_group(trade: dict, present: list[str], missing: list[str],
                    netted: list[str]) -> str:
    status = str(trade.get("status") or "")
    if status == "closed":
        return "closed"
    if status not in ACTIVE_STATUSES:
        return "manual_review"
    unexplained_missing = [s for s in missing if s not in netted]
    if not missing:
        if trade.get("flat_observation_count"):
            return "flat_pending_confirmation"
        if trade.get("exit_pending_reason"):
            return "exit_pending"
        if status == "closing":
            return "closing"
        return "open"
    if not present:
        return "flat_pending_confirmation"
    if netted and not unexplained_missing:
        # Legs exist economically but net against another group at the broker.
        return "manual_review"
    return "partially_closed"


def reconcile(trades: list[dict], broker_positions: list[dict]) -> dict:
    """Read-only, quantity-aware reconciliation of durable state vs broker.

    trades: full trade list from options-trades.json (all statuses).
    broker_positions: [{"symbol": occ, "qty": signed float}, ...]

    Returns a report dict. Never mutates inputs. entries_allowed is False on
    any discrepancy that is not fully self-consistent.
    """
    trades = [t for t in trades if isinstance(t, dict)]
    active = [t for t in trades if t.get("status") in ACTIVE_STATUSES]
    closed = [t for t in trades if t.get("status") == "closed"]

    # Accept option-looking symbols plus anything a tracked trade references,
    # while excluding unrelated broker holdings (e.g. wheel equity shares).
    tracked_leg_symbols = {
        str(leg) for t in trades for leg in (t.get("legs") or [])
    }
    broker: dict[str, int] = {}
    for pos in broker_positions:
        if not isinstance(pos, dict):
            continue
        symbol = str(pos.get("symbol") or "")
        if not OCC_RE.match(symbol) and symbol not in tracked_leg_symbols:
            continue
        try:
            broker[symbol] = broker.get(symbol, 0) + int(round(float(pos.get("qty") or 0)))
        except (TypeError, ValueError):
            continue

    expected = signed_book(active)
    all_symbols = sorted(set(expected) | set(broker))
    residual = {
        symbol: broker.get(symbol, 0) - expected.get(symbol, 0)
        for symbol in all_symbols
        if broker.get(symbol, 0) != expected.get(symbol, 0)
    }

    # Try to explain residuals with closed trades that may still be open at
    # the broker (deterministic order: most recently closed first, subsets
    # of bounded size so behavior stays predictable).
    explanations = _explain_residual(residual, closed)
    explained_ids = {e["trade_id"] for e in explanations}
    explained_book: dict[str, int] = {}
    for e in explanations:
        for symbol, qty in e["book"].items():
            explained_book[symbol] = explained_book.get(symbol, 0) + qty
    unexplained = {
        symbol: qty - explained_book.get(symbol, 0)
        for symbol, qty in residual.items()
        if qty - explained_book.get(symbol, 0) != 0
    }

    # Netted symbols: expected non-zero contribution from >= 2 groups with
    # opposite sides, so the broker shows less than each group's exposure.
    per_group_books = {str(t.get("id") or t.get("label") or "?"): signed_book([t]) for t in active}
    for e in explanations:
        per_group_books[e["trade_id"]] = e["book"]
    netted_symbols: list[str] = []
    if per_group_books:
        universe: set[str] = set()
        for book in per_group_books.values():
            universe.update(book)
        for symbol in sorted(universe):
            contribs = [book.get(symbol, 0) for book in per_group_books.values() if book.get(symbol)]
            if len(contribs) > 1 and abs(sum(contribs)) < sum(abs(c) for c in contribs):
                netted_symbols.append(symbol)

    # Duplicate active ownership (same OCC symbol in >1 active group).
    owners: dict[str, list[str]] = {}
    for trade in active:
        tid = str(trade.get("id") or trade.get("label") or "?")
        for leg in trade.get("legs") or []:
            owners.setdefault(str(leg), []).append(tid)
    duplicate_active_legs = sorted(s for s, o in owners.items() if len(o) > 1)

    # Closed trades whose legs are still (economically) open at the broker.
    closed_still_open = sorted({
        symbol
        for e in explanations
        for symbol in e["book"]
    })

    # Per-group classification.
    group_states = {}
    findings: list[str] = []
    for trade in active:
        tid = str(trade.get("id") or trade.get("label") or "?")
        legs = [str(s) for s in trade.get("legs") or []]
        present = [s for s in legs if broker.get(s, 0) != 0]
        missing = [s for s in legs if broker.get(s, 0) == 0]
        netted = [s for s in missing if s in netted_symbols]
        state = _classify_group(trade, present, missing, netted)
        group_states[tid] = {
            "label": trade.get("label"),
            "status": trade.get("status"),
            "state": state,
            "legs_present": present,
            "legs_missing": missing,
            "legs_netted": netted,
        }
        if netted:
            findings.append(
                f"group {tid} legs {netted} net to zero at broker against an "
                "opposite-side group; per-symbol positions cannot confirm them"
            )
        elif missing:
            findings.append(f"group {tid} missing broker legs {missing}")

    for e in explanations:
        findings.append(
            f"closed trade {e['trade_id']} ({e['label']}) still open at broker: "
            f"{sorted(e['book'])}"
        )
        group_states[e["trade_id"]] = {
            "label": e["label"],
            "status": "closed",
            "state": "manual_review",
            "legs_present": sorted(e["book"]),
            "legs_missing": [],
            "legs_netted": [s for s in e["book"] if s in netted_symbols],
        }

    if duplicate_active_legs:
        findings.append(f"duplicate active ownership of legs {duplicate_active_legs}")
    for symbol, qty in sorted(unexplained.items()):
        findings.append(f"unexplained broker residual {symbol} qty={qty:+d}")

    ok = not findings
    return {
        "status": "ok" if ok else "review_required",
        "entries_allowed": ok,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "active_groups": len(active),
        "expected_book": expected,
        "broker_book": broker,
        "residual": residual,
        "netted_symbols": netted_symbols,
        "duplicate_active_legs": duplicate_active_legs,
        "closed_trade_legs_still_open": closed_still_open,
        "closed_groups_still_open": sorted(explained_ids),
        "unexplained_residual": unexplained,
        "group_states": group_states,
        "findings": findings,
    }


def _explain_residual(residual: dict[str, int], closed_trades: list[dict]) -> list[dict]:
    """Find closed trades whose books exactly explain the broker residual.

    Deterministic bounded search: candidates are closed trades sharing at
    least one residual symbol, most recently closed first, at most 12
    candidates, subsets up to size 3. Requires an exact match of every
    residual symbol (no partial credit) so we never guess.
    """
    if not residual:
        return []
    candidates = []
    for trade in closed_trades:
        book = signed_book([{**trade, "status": "open"}])
        if any(symbol in residual for symbol in book):
            candidates.append({
                "trade_id": str(trade.get("id") or trade.get("label") or "?"),
                "label": str(trade.get("label") or ""),
                "closed_at": str(trade.get("closed_at") or ""),
                "book": book,
            })
    candidates.sort(key=lambda c: c["closed_at"], reverse=True)
    candidates = candidates[:12]

    from itertools import combinations

    for size in (1, 2, 3):
        for combo in combinations(candidates, size):
            combined: dict[str, int] = {}
            for c in combo:
                for symbol, qty in c["book"].items():
                    combined[symbol] = combined.get(symbol, 0) + qty
            combined = {s: q for s, q in combined.items() if q}
            if combined == {s: q for s, q in residual.items() if q}:
                return list(combo)
    return []


# ── Atomic, lock-safe durable state writes ─────────────────────────────────────
class StateLockTimeout(RuntimeError):
    pass


def _lock_path(path: Path) -> Path:
    return path.with_name(path.name + ".lock")


def atomic_save_json(path: Path | str, data: Any, *, lock_timeout: float = 10.0,
                     stale_lock_seconds: float = 60.0) -> None:
    """Write JSON durably: exclusive lock file + temp write + os.replace.

    A crash mid-write can never leave a truncated state file, and two writers
    cannot interleave. A lock older than stale_lock_seconds is considered
    abandoned (crashed process) and is broken.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = _lock_path(path)
    deadline = time.monotonic() + lock_timeout
    fd = None
    tmp: Path | None = None
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            try:
                age = time.time() - lock.stat().st_mtime
                if age > stale_lock_seconds:
                    lock.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise StateLockTimeout(f"could not lock {path} within {lock_timeout}s")
            time.sleep(0.1)
    try:
        os.write(fd, str(os.getpid()).encode("ascii", "ignore"))
        # Multiple scheduler threads share a PID on Windows. A PID-only temp
        # name lets concurrent writers overwrite or replace each other's file.
        tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}-{time.time_ns()}")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
        try:
            os.close(fd)
        except OSError:
            pass
        lock.unlink(missing_ok=True)
