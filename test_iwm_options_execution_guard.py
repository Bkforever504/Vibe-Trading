from pathlib import Path
import types
from datetime import date, datetime, timedelta, timezone


def _fake_pos(symbol, avg_entry_price, qty, unrealized_pl):
    p = types.SimpleNamespace()
    p.symbol = symbol
    p.avg_entry_price = str(avg_entry_price)
    p.qty = str(qty)
    p.unrealized_pl = str(unrealized_pl)
    p.asset_class = "us_option"
    return p


def test_default_credit_stop_is_one_times_credit():
    from strategies import iwm_options_bot

    assert iwm_options_bot.STOP_LOSS_PCT == -1.0
    assert iwm_options_bot._trade_stop_loss_pct({"strategy": "put_spread"}) == -1.0


def test_stop_loss_triggers_at_100pct_of_credit(monkeypatch, tmp_path):
    """Stop fires at -100% of credit; position must not reach -211%."""
    from strategies import iwm_options_bot

    trade = {
        "id": "t1", "status": "open", "label": "Test PS",
        "strategy": "put_spread", "legs": ["IWM260717P00190000"],
        "net_credit": 1.00,   # $1.00/contract × 100 = $100 credit
        "qty": 1,
        "profit_close_pct": 0.5,
        "stop_loss_pct": -1.0,
    }
    pos = _fake_pos("IWM260717P00190000", avg_entry_price=1.00, qty=-1, unrealized_pl=-100.00)
    state = {"trades": [trade]}

    closed = []

    monkeypatch.setattr(iwm_options_bot, "_load_trade_state", lambda: state)
    monkeypatch.setattr(iwm_options_bot, "_save_trade_state", lambda s: None)
    monkeypatch.setattr(iwm_options_bot, "_recover_untracked_mleg_groups", lambda c, s: False)
    monkeypatch.setattr(iwm_options_bot, "_can_submit_option_close_orders", lambda: True)
    monkeypatch.setattr(iwm_options_bot, "AUTO_CLOSE_GROUPS", True)
    monkeypatch.setattr(iwm_options_bot, "_alert", lambda msg: None)

    def fake_close_group(client, t, reason):
        closed.append(reason)
        return True

    monkeypatch.setattr(iwm_options_bot, "_close_trade_group", fake_close_group)

    class FakeClient:
        def get_all_positions(self):
            return [pos]

    iwm_options_bot.monitor_and_close(FakeClient())

    assert closed, "stop loss did not trigger"
    assert "stop loss" in closed[0]


def test_stop_loss_triggers_when_net_credit_zero(monkeypatch, tmp_path):
    """When net_credit=0 (recovered trade gap), fall back to cost basis for stop calculation."""
    from strategies import iwm_options_bot

    trade = {
        "id": "t2", "status": "open", "label": "Recovered MLEG [IWM]",
        "strategy": "recovered_mleg", "legs": ["IWM260717P00190000"],
        "net_credit": 0.0,   # missing fill data → credit unknown
        "qty": 1,
        "profit_close_pct": 0.5,
        "stop_loss_pct": -1.0,
    }
    # Cost basis = $1.00 entry × 1 qty × 100 = $100; P&L = -$100 → -100%
    pos = _fake_pos("IWM260717P00190000", avg_entry_price=1.00, qty=-1, unrealized_pl=-100.00)
    state = {"trades": [trade]}

    closed = []
    monkeypatch.setattr(iwm_options_bot, "_load_trade_state", lambda: state)
    monkeypatch.setattr(iwm_options_bot, "_save_trade_state", lambda s: None)
    monkeypatch.setattr(iwm_options_bot, "_recover_untracked_mleg_groups", lambda c, s: False)
    monkeypatch.setattr(iwm_options_bot, "_can_submit_option_close_orders", lambda: True)
    monkeypatch.setattr(iwm_options_bot, "AUTO_CLOSE_GROUPS", True)
    monkeypatch.setattr(iwm_options_bot, "_alert", lambda msg: None)

    def fake_close_group(client, t, reason):
        closed.append(reason)
        return True

    monkeypatch.setattr(iwm_options_bot, "_close_trade_group", fake_close_group)

    class FakeClient:
        def get_all_positions(self):
            return [pos]

    iwm_options_bot.monitor_and_close(FakeClient())

    assert closed, "stop loss did not trigger even with cost-basis fallback"
    assert "stop loss" in closed[0]
    assert "cost_basis" in closed[0]


def test_near_target_credit_spread_waits_before_cutoff(monkeypatch, tmp_path):
    """A 46% credit win should not close before the late-day protection window."""
    from strategies import iwm_options_bot

    trade = {
        "id": "t3", "status": "open", "label": "Put Spread [IWM]",
        "strategy": "put_spread", "legs": ["IWM1", "IWM2"],
        "net_credit": 0.52,
        "qty": 3,
        "profit_close_pct": 0.5,
        "stop_loss_pct": -1.0,
    }
    state = {"trades": [trade]}
    positions = [
        _fake_pos("IWM1", avg_entry_price=1.00, qty=-3, unrealized_pl=120.00),
        _fake_pos("IWM2", avg_entry_price=0.48, qty=3, unrealized_pl=-48.00),
    ]

    closed = []
    monkeypatch.setattr(iwm_options_bot, "_load_trade_state", lambda: state)
    monkeypatch.setattr(iwm_options_bot, "_save_trade_state", lambda s: None)
    monkeypatch.setattr(iwm_options_bot, "_recover_untracked_mleg_groups", lambda c, s: False)
    monkeypatch.setattr(iwm_options_bot, "_can_submit_option_close_orders", lambda: True)
    monkeypatch.setattr(iwm_options_bot, "AUTO_CLOSE_GROUPS", True)
    monkeypatch.setattr(iwm_options_bot, "_alert", lambda msg: None)
    monkeypatch.setattr(iwm_options_bot, "_now_et", lambda: datetime(2026, 7, 1, 11, 30))
    monkeypatch.setattr(
        iwm_options_bot,
        "_close_trade_group",
        lambda client, t, reason: closed.append(reason) or True,
    )

    class FakeClient:
        def get_all_positions(self):
            return positions

    iwm_options_bot.monitor_and_close(FakeClient())

    assert closed == []
    assert state["trades"][0]["status"] == "open"


def test_near_target_credit_spread_closes_after_cutoff(monkeypatch, tmp_path):
    """A 46% credit win closes after noon ET instead of risking overnight giveback."""
    from strategies import iwm_options_bot

    trade = {
        "id": "t4", "status": "open", "label": "Put Spread [IWM]",
        "strategy": "put_spread", "legs": ["IWM1", "IWM2"],
        "net_credit": 0.52,
        "qty": 3,
        "profit_close_pct": 0.5,
        "stop_loss_pct": -1.0,
    }
    state = {"trades": [trade]}
    positions = [
        _fake_pos("IWM1", avg_entry_price=1.00, qty=-3, unrealized_pl=120.00),
        _fake_pos("IWM2", avg_entry_price=0.48, qty=3, unrealized_pl=-48.00),
    ]

    closed = []
    monkeypatch.setattr(iwm_options_bot, "_load_trade_state", lambda: state)
    monkeypatch.setattr(iwm_options_bot, "_save_trade_state", lambda s: None)
    monkeypatch.setattr(iwm_options_bot, "_recover_untracked_mleg_groups", lambda c, s: False)
    monkeypatch.setattr(iwm_options_bot, "_can_submit_option_close_orders", lambda: True)
    monkeypatch.setattr(iwm_options_bot, "AUTO_CLOSE_GROUPS", True)
    monkeypatch.setattr(iwm_options_bot, "_alert", lambda msg: None)
    monkeypatch.setattr(iwm_options_bot, "_now_et", lambda: datetime(2026, 7, 1, 12, 30))
    monkeypatch.setattr(
        iwm_options_bot,
        "_close_trade_group",
        lambda client, t, reason: closed.append(reason) or True,
    )

    class FakeClient:
        def get_all_positions(self):
            return positions

    iwm_options_bot.monitor_and_close(FakeClient())

    assert closed, "near-target protection did not trigger"
    assert "near-target protection" in closed[0]
    assert state["trades"][0]["status"] == "closing"


def test_iron_condor_21_dte_rolls_instead_of_full_close(monkeypatch, tmp_path):
    from strategies import iwm_options_bot

    expiry = date.today() + timedelta(days=21)
    legs = ["IWM260807P00210000", "IWM260807P00207000", "IWM260807C00230000", "IWM260807C00233000"]
    trade = {
        "id": "ic1",
        "status": "open",
        "label": "Iron Condor [IWM]",
        "strategy": "iron_condor",
        "underlying": "IWM",
        "legs": legs,
        "net_credit": 1.00,
        "qty": 1,
        "profit_close_pct": 0.5,
        "stop_loss_pct": -1.0,
        "expiry": str(expiry),
    }
    state = {"trades": [trade]}
    rolled = []
    closed = []

    monkeypatch.setattr(iwm_options_bot, "_load_trade_state", lambda: state)
    monkeypatch.setattr(iwm_options_bot, "_save_trade_state", lambda s: None)
    monkeypatch.setattr(iwm_options_bot, "_recover_untracked_mleg_groups", lambda c, s: False)
    monkeypatch.setattr(iwm_options_bot, "_can_submit_option_close_orders", lambda: True)
    monkeypatch.setattr(iwm_options_bot, "AUTO_CLOSE_GROUPS", True)
    monkeypatch.setattr(iwm_options_bot, "_alert", lambda msg: None)
    monkeypatch.setattr(iwm_options_bot, "_close_trade_group", lambda *args: closed.append(args) or True)
    monkeypatch.setattr(iwm_options_bot, "_submit_ic_roll", lambda *args: rolled.append(args) or True)

    class FakeClient:
        def get_all_positions(self):
            return [_fake_pos(symbol, avg_entry_price=1.00, qty=-1, unrealized_pl=0.0) for symbol in legs]

    iwm_options_bot.monitor_and_close(FakeClient(), object())

    assert rolled, "21-DTE iron condor did not attempt a roll"
    assert not closed, "21-DTE iron condor should not full-close the group"


def test_netted_group_closes_as_reversed_mleg(monkeypatch):
    from strategies import iwm_options_bot

    legs = ["IWM1", "IWM2", "IWM3", "IWM4"]
    trade = {
        "id": "group-1234",
        "label": "Iron Condor [IWM]",
        "strategy": "iron_condor",
        "status": "open",
        "legs": legs,
        "qty": 2,
        "net_credit": 0.62,
        "max_risk_per_contract": 138.0,
        "quote_mark": {
            "status": "ok",
            "marked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "natural_close_debit": 0.44,
            "netted_legs": ["IWM1"],
            "close_plan": {
                "status": "ok",
                "proof": "exact_signed_book_transition",
                "transition_legs": ["IWM1"],
                "legs": [
                    {"symbol": "IWM1", "side": "buy", "ratio_qty": "1", "position_intent": "buy_to_open"},
                    {"symbol": "IWM2", "side": "sell", "ratio_qty": "1", "position_intent": "sell_to_close"},
                    {"symbol": "IWM3", "side": "buy", "ratio_qty": "1", "position_intent": "buy_to_close"},
                    {"symbol": "IWM4", "side": "sell", "ratio_qty": "1", "position_intent": "sell_to_close"},
                ],
            },
            "legs": [
                {"symbol": "IWM1", "close_side": "buy", "ratio_qty": 1},
                {"symbol": "IWM2", "close_side": "sell", "ratio_qty": 1},
                {"symbol": "IWM3", "close_side": "buy", "ratio_qty": 1},
                {"symbol": "IWM4", "close_side": "sell", "ratio_qty": 1},
            ],
        },
    }
    submitted = []

    def fake_post(body, label, *, risk_reducing_close=False):
        submitted.append((body, label, risk_reducing_close))
        return {"id": "close-order"}

    monkeypatch.setattr(iwm_options_bot, "_post_order_with_retry", fake_post)

    class FakeClient:
        def close_position(self, symbol):
            raise AssertionError(f"symbol close must not be used for netted group: {symbol}")

    assert iwm_options_bot._close_trade_group(FakeClient(), trade, "profit target") is True
    body, _, risk_reducing = submitted[0]
    assert risk_reducing is True
    assert body["order_class"] == "mleg"
    assert body["limit_price"] == "0.44"
    assert body["qty"] == "2"
    assert [leg["side"] for leg in body["legs"]] == ["buy", "sell", "buy", "sell"]
    assert [leg["position_intent"] for leg in body["legs"]] == [
        "buy_to_open", "sell_to_close", "buy_to_close", "sell_to_close",
    ]
    assert trade["closing_order_id"] == "close-order"


def test_netted_group_refuses_close_without_reconciled_transition_plan(monkeypatch):
    from strategies import iwm_options_bot

    trade = {
        "id": "group-unsafe",
        "label": "Iron Condor [IWM]",
        "strategy": "iron_condor",
        "status": "open",
        "legs": ["IWM1", "IWM2"],
        "qty": 1,
        "net_credit": 0.50,
        "quote_mark": {
            "status": "ok",
            "marked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "natural_close_debit": 0.25,
            "netted_legs": ["IWM1"],
            "legs": [
                {"symbol": "IWM1", "close_side": "buy", "ratio_qty": 1},
                {"symbol": "IWM2", "close_side": "sell", "ratio_qty": 1},
            ],
        },
    }
    submitted = []
    monkeypatch.setattr(
        iwm_options_bot,
        "_post_order_with_retry",
        lambda *args, **kwargs: submitted.append((args, kwargs)),
    )

    assert iwm_options_bot._close_trade_group(object(), trade, "profit target") is False
    assert submitted == []


def test_filled_mleg_close_retires_exact_economic_group(monkeypatch):
    from strategies import iwm_options_bot

    trade = {
        "id": "group-filled",
        "label": "Iron Condor [IWM]",
        "status": "closing",
        "legs": ["IWM1", "IWM2", "IWM3", "IWM4"],
        "qty": 2,
        "closing_order_id": "close-filled",
    }
    state = {"trades": [trade]}
    monkeypatch.setattr(
        iwm_options_bot,
        "_order_snapshot",
        lambda order_id: {
            "id": order_id,
            "status": "filled",
            "order_class": "mleg",
            "filled_qty": "2",
            "filled_avg_price": "0.39",
            "filled_at": "2026-07-14T17:00:04Z",
            "legs": [{"symbol": symbol} for symbol in trade["legs"]],
        },
    )

    assert iwm_options_bot._refresh_filled_group_closes(state) is True
    assert trade["status"] == "closed"
    assert trade["closed_at"] == "2026-07-14T17:00:04Z"
    assert trade["closing_order_status"] == "filled"
    assert trade["closing_filled_avg_price"] == 0.39
    assert trade["close_verified_by"] == "alpaca_filled_mleg_order"


def test_filled_close_with_wrong_legs_stays_closing(monkeypatch):
    from strategies import iwm_options_bot

    trade = {
        "id": "group-mismatch",
        "label": "Iron Condor [IWM]",
        "status": "closing",
        "legs": ["IWM1", "IWM2"],
        "qty": 1,
        "closing_order_id": "close-wrong",
    }
    monkeypatch.setattr(
        iwm_options_bot,
        "_order_snapshot",
        lambda order_id: {
            "id": order_id,
            "status": "filled",
            "order_class": "mleg",
            "filled_qty": "1",
            "legs": [{"symbol": "IWM1"}, {"symbol": "OTHER"}],
        },
    )

    assert iwm_options_bot._refresh_filled_group_closes({"trades": [trade]}) is False
    assert trade["status"] == "closing"


def test_place_mleg_blocks_low_confidence_before_alpaca_submit(monkeypatch, tmp_path: Path) -> None:
    from strategies import iwm_options_bot

    monkeypatch.setattr(iwm_options_bot, "DEFAULT_BLOCK_FILE", tmp_path / "manual_reset.json")
    monkeypatch.setattr(iwm_options_bot, "REQUIRE_MANUAL_APPROVAL", False)
    monkeypatch.setattr(iwm_options_bot, "PAPER", True)
    monkeypatch.setattr(iwm_options_bot, "_alert", lambda message: None)

    submitted = []
    monkeypatch.setattr(
        iwm_options_bot,
        "_post_order_with_retry",
        lambda body, label: submitted.append((body, label)) or {"id": "bad"},
    )

    ok = iwm_options_bot._place_mleg(
        legs_payload=[
            {"symbol": "IWM260717P00190000", "side": "sell", "ratio_qty": "1"},
            {"symbol": "IWM260717P00187000", "side": "buy", "ratio_qty": "1"},
        ],
        limit_price=0.50,
        qty=1,
        label="Put Spread [IWM]",
        trade_meta={
            "strategy": "put_spread",
            "underlying": "IWM",
            "max_risk_per_contract": 250,
            "candidate_confidence": {"score": 7, "reasons": ["test low confidence"]},
        },
    )

    assert ok is False
    assert submitted == []


def test_iwm_vix_filter_uses_cboe_term_structure_context(monkeypatch) -> None:
    from strategies import iwm_options_bot

    monkeypatch.setattr(
        iwm_options_bot,
        "fetch_vix_term_structure_context",
        lambda: {
            "source": "cboe_vix_vix3m_history",
            "date": "2026-06-26",
            "vix": 18.0,
            "vix3m": 22.0,
            "vix_over_vix3m": 0.8182,
            "regime": "contango",
        },
    )

    assert iwm_options_bot._vix_in_range() is True
    assert iwm_options_bot._JOURNAL_VIX == 18.0
    assert iwm_options_bot._JOURNAL_VIX_TERM_RATIO == 0.8182
