"""Tests for strategies/options_state.py and the hardened bot state handling.

The reconciliation fixtures reproduce the real 2026-07-07 incident: a single
transient flat broker snapshot marked every tracked group closed, a new IWM
iron condor was opened seconds later sharing the P277 strike with the old
condor, and the P277 legs netted to zero at the broker.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies import options_state


# ── Incident fixtures (real symbols/quantities from 2026-07-07) ────────────────
OLD_CONDOR = {
    "id": "1733badd-f177-4b51-92fb-14e759280934",
    "label": "Iron Condor [IWM]",
    "strategy": "iron_condor",
    "underlying": "IWM",
    "status": "closed",  # wrongly closed by the flat-snapshot bug
    "closed_at": "2026-07-07T14:45:03Z",
    "qty": 2,
    "legs": [
        "IWM260807P00279000",
        "IWM260807P00277000",
        "IWM260807C00317500",
        "IWM260807C00320000",
    ],
}

NEW_CONDOR = {
    "id": "d72ded80-b97f-4fb4-a6a7-d3c0d77ddc51",
    "label": "Iron Condor [IWM]",
    "strategy": "iron_condor",
    "underlying": "IWM",
    "status": "open",
    "qty": 2,
    "legs": [
        "IWM260807P00277000",
        "IWM260807P00275000",
        "IWM260807C00313000",
        "IWM260807C00315000",
    ],
}

# Broker truth: P277 nets to zero (old long +2 vs new short -2).
BROKER_POSITIONS = [
    {"symbol": "IWM260807C00313000", "qty": -2},
    {"symbol": "IWM260807C00315000", "qty": 2},
    {"symbol": "IWM260807C00317500", "qty": -2},
    {"symbol": "IWM260807C00320000", "qty": 2},
    {"symbol": "IWM260807P00275000", "qty": 2},
    {"symbol": "IWM260807P00279000", "qty": -2},
]


# ── Leg inference ──────────────────────────────────────────────────────────────
def test_iron_condor_side_inference_matches_convention() -> None:
    details = options_state.infer_leg_details(NEW_CONDOR)
    by_symbol = {d["symbol"]: d for d in details}
    assert by_symbol["IWM260807P00277000"]["side"] == "sell"
    assert by_symbol["IWM260807P00275000"]["side"] == "buy"
    assert by_symbol["IWM260807C00313000"]["side"] == "sell"
    assert by_symbol["IWM260807C00315000"]["side"] == "buy"
    assert all(d["qty"] == 2 for d in details)
    assert all(d["inferred"] for d in details)


def test_explicit_leg_details_take_precedence_over_inference() -> None:
    trade = dict(NEW_CONDOR)
    trade["leg_details"] = [
        {"symbol": "IWM260807P00277000", "side": "sell", "ratio_qty": 1},
        {"symbol": "IWM260807P00275000", "side": "buy", "ratio_qty": 1},
    ]
    details = options_state.infer_leg_details(trade)
    assert len(details) == 2
    assert not any(d["inferred"] for d in details)
    assert details[0]["qty"] == 2  # group qty x ratio


def test_quote_mark_prices_all_netted_group_legs() -> None:
    trade = {**NEW_CONDOR, "net_credit": 0.62}
    quotes = {
        "IWM260807P00277000": {"bid": 0.80, "ask": 0.82},
        "IWM260807P00275000": {"bid": 0.50, "ask": 0.52},
        "IWM260807C00313000": {"bid": 0.28, "ask": 0.30},
        "IWM260807C00315000": {"bid": 0.18, "ask": 0.20},
    }

    mark = options_state.quote_mark(trade, quotes)

    assert mark["status"] == "ok"
    assert mark["midpoint_close_debit"] == 0.4
    assert mark["natural_close_debit"] == 0.44
    assert mark["pnl_dollars"] == 44.0
    assert mark["pnl_pct_of_credit"] == 0.354839
    assert {leg["close_side"] for leg in mark["legs"]} == {"buy", "sell"}


def test_quote_mark_fails_closed_when_any_leg_quote_is_missing() -> None:
    trade = {**NEW_CONDOR, "net_credit": 0.62}
    mark = options_state.quote_mark(
        trade,
        {symbol: {"bid": 0.20, "ask": 0.22} for symbol in trade["legs"][:-1]},
    )

    assert mark["status"] == "unavailable"
    assert mark["reason"] == "incomplete_leg_quotes"
    assert mark["missing_quotes"] == [trade["legs"][-1]]


def test_old_condor_close_plan_opens_surviving_short_netted_leg() -> None:
    old = {**OLD_CONDOR, "status": "open"}
    new = {**NEW_CONDOR, "status": "open"}

    plan = options_state.close_transition_plan(old, [old, new], BROKER_POSITIONS)

    assert plan["status"] == "ok"
    assert plan["proof"] == "exact_signed_book_transition"
    assert plan["transition_legs"] == ["IWM260807P00277000"]
    by_symbol = {leg["symbol"]: leg for leg in plan["legs"]}
    assert by_symbol["IWM260807P00277000"]["position_intent"] == "sell_to_open"
    assert by_symbol["IWM260807P00279000"]["position_intent"] == "buy_to_close"
    assert by_symbol["IWM260807C00317500"]["position_intent"] == "buy_to_close"
    assert by_symbol["IWM260807C00320000"]["position_intent"] == "sell_to_close"
    assert plan["expected_book_after"] == options_state.signed_book([new])


def test_new_condor_close_plan_opens_surviving_long_netted_leg() -> None:
    old = {**OLD_CONDOR, "status": "open"}
    new = {**NEW_CONDOR, "status": "open"}

    plan = options_state.close_transition_plan(new, [old, new], BROKER_POSITIONS)

    assert plan["status"] == "ok"
    assert plan["transition_legs"] == ["IWM260807P00277000"]
    by_symbol = {leg["symbol"]: leg for leg in plan["legs"]}
    assert by_symbol["IWM260807P00277000"]["position_intent"] == "buy_to_open"
    assert by_symbol["IWM260807P00275000"]["position_intent"] == "sell_to_close"
    assert by_symbol["IWM260807C00313000"]["position_intent"] == "buy_to_close"
    assert by_symbol["IWM260807C00315000"]["position_intent"] == "sell_to_close"
    assert plan["expected_book_after"] == options_state.signed_book([old])


def test_close_plan_fails_closed_on_unexplained_broker_mismatch() -> None:
    old = {**OLD_CONDOR, "status": "open"}
    new = {**NEW_CONDOR, "status": "open"}
    mismatched = [*BROKER_POSITIONS, {"symbol": "IWM260807P00277000", "qty": 1}]

    plan = options_state.close_transition_plan(old, [old, new], mismatched)

    assert plan["status"] == "unavailable"
    assert plan["reason"] == "signed_book_mismatch"
    assert plan["residual"] == {"IWM260807P00277000": 1}


def test_recovered_group_sides_inferred_from_strikes() -> None:
    trade = {
        "id": "r1",
        "strategy": "recovered_mleg",
        "status": "open",
        "qty": 3,
        "legs": ["PLTR260710P00124000", "PLTR260710P00121000"],
    }
    details = {d["symbol"]: d for d in options_state.infer_leg_details(trade)}
    assert details["PLTR260710P00124000"]["side"] == "sell"  # higher strike put
    assert details["PLTR260710P00121000"]["side"] == "buy"


# ── Reconciliation: the 2026-07-07 incident ───────────────────────────────────
def test_incident_reconciliation_finds_netting_and_closed_but_open_group() -> None:
    report = options_state.reconcile([OLD_CONDOR, NEW_CONDOR], BROKER_POSITIONS)

    assert report["status"] == "review_required"
    assert report["entries_allowed"] is False
    # The shared strike is identified as netted, not "missing".
    assert "IWM260807P00277000" in report["netted_symbols"]
    # The wrongly-closed condor is identified as still open at the broker.
    assert OLD_CONDOR["id"] in report["closed_groups_still_open"]
    # Every broker residual is explained: nothing left unexplained.
    assert report["unexplained_residual"] == {}
    # The active group is flagged for manual review, not treated as clean.
    assert report["group_states"][NEW_CONDOR["id"]]["state"] == "manual_review"
    assert report["group_states"][OLD_CONDOR["id"]]["state"] == "manual_review"


def test_clean_book_reconciles_and_allows_entries() -> None:
    trade = {
        "id": "ps1",
        "label": "Put Spread [IWM]",
        "strategy": "put_spread",
        "status": "open",
        "qty": 3,
        "legs": ["IWM260709P00289000", "IWM260709P00286000"],
    }
    broker = [
        {"symbol": "IWM260709P00289000", "qty": -3},
        {"symbol": "IWM260709P00286000", "qty": 3},
    ]
    report = options_state.reconcile([trade], broker)
    assert report["status"] == "ok"
    assert report["entries_allowed"] is True
    assert report["group_states"]["ps1"]["state"] == "open"


def test_partial_close_is_flagged_not_silently_closed() -> None:
    trade = {
        "id": "ps2",
        "strategy": "put_spread",
        "status": "open",
        "qty": 3,
        "legs": ["IWM260709P00289000", "IWM260709P00286000"],
    }
    broker = [{"symbol": "IWM260709P00286000", "qty": 3}]  # short leg gone
    report = options_state.reconcile([trade], broker)
    assert report["entries_allowed"] is False
    assert report["group_states"]["ps2"]["state"] == "partially_closed"


def test_duplicate_active_ownership_detected() -> None:
    a = dict(NEW_CONDOR, id="a", status="open")
    b = dict(NEW_CONDOR, id="b", status="open")
    report = options_state.reconcile([a, b], BROKER_POSITIONS)
    assert report["duplicate_active_legs"]
    assert report["entries_allowed"] is False


def test_unexplained_residual_fails_closed() -> None:
    broker = BROKER_POSITIONS + [{"symbol": "IWM260807C00330000", "qty": 5}]
    report = options_state.reconcile([OLD_CONDOR, NEW_CONDOR], broker)
    assert "IWM260807C00330000" in report["unexplained_residual"]
    assert report["entries_allowed"] is False


def test_reconcile_does_not_mutate_inputs() -> None:
    trades = [json.loads(json.dumps(OLD_CONDOR)), json.loads(json.dumps(NEW_CONDOR))]
    snapshot = json.loads(json.dumps(trades))
    options_state.reconcile(trades, BROKER_POSITIONS)
    assert trades == snapshot


# ── Atomic, lock-safe writes ───────────────────────────────────────────────────
def test_atomic_save_json_writes_valid_json_and_cleans_up(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    options_state.atomic_save_json(target, {"trades": [1, 2, 3]})
    assert json.loads(target.read_text(encoding="utf-8")) == {"trades": [1, 2, 3]}
    leftovers = [p for p in tmp_path.iterdir() if p.name != "state.json"]
    assert leftovers == []


def test_atomic_save_json_lock_contention_times_out(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    lock = tmp_path / "state.json.lock"
    lock.write_text("held", encoding="utf-8")
    started = time.monotonic()
    try:
        options_state.atomic_save_json(
            target, {"x": 1}, lock_timeout=0.5, stale_lock_seconds=3600
        )
        raise AssertionError("expected StateLockTimeout")
    except options_state.StateLockTimeout:
        pass
    assert time.monotonic() - started >= 0.5
    assert not target.exists()


def test_atomic_save_json_breaks_stale_lock(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    lock = tmp_path / "state.json.lock"
    lock.write_text("crashed-writer", encoding="utf-8")
    old = time.time() - 3600
    import os

    os.utime(lock, (old, old))
    options_state.atomic_save_json(target, {"ok": True}, stale_lock_seconds=60)
    assert json.loads(target.read_text(encoding="utf-8")) == {"ok": True}


def test_concurrent_writers_never_corrupt_state(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    errors: list[Exception] = []

    def writer(n: int) -> None:
        try:
            options_state.atomic_save_json(target, {"writer": n, "rows": list(range(200))},
                                           lock_timeout=10)
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["rows"] == list(range(200))


# ── Flat confirmation requires real time separation ───────────────────────────
def test_confirm_flat_trade_requires_two_observations_and_elapsed_time() -> None:
    from strategies import iwm_options_bot as bot

    trade = {"status": "open"}
    t0 = datetime(2026, 7, 7, 14, 45, 3, tzinfo=timezone.utc)

    # First flat snapshot: never closes.
    assert bot._confirm_flat_trade(trade, now=t0) is False
    assert trade["status"] == "open"

    # Second snapshot 5 seconds later (API retry burst): still blocked.
    assert bot._confirm_flat_trade(trade, now=t0 + timedelta(seconds=5)) is False
    assert trade["status"] == "open"

    # Second snapshot after the minimum separation: allowed to close.
    late = t0 + timedelta(seconds=bot.FLAT_CONFIRM_MIN_SECONDS + 1)
    assert bot._confirm_flat_trade(trade, now=late) is True
    assert trade["status"] == "closed"
    assert "flat_observation_count" not in trade
    assert "flat_first_observed_at" not in trade


def test_clear_flat_observation_resets_all_markers() -> None:
    from strategies import iwm_options_bot as bot

    trade = {
        "status": "open",
        "flat_observation_count": 1,
        "flat_observed_at": "2026-07-07T14:45:03Z",
        "flat_first_observed_at": "2026-07-07T14:45:03Z",
    }
    assert bot._clear_flat_observation(trade) is True
    assert "flat_observation_count" not in trade
    assert "flat_first_observed_at" not in trade
