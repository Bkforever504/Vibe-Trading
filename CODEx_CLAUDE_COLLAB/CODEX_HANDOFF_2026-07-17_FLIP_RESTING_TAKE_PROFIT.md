# Flip Resting Take-Profit Handoff

Date: 2026-07-17 CT  
Repository: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`  
Execution posture: Alpaca paper by default; no live authority or threshold changes.

## Delivered

Primary implementation:

```text
strategies\flip_bot.py
```

Regression coverage:

```text
agent\tests\test_flip_bot_safety.py
agent\tests\test_flip_entry_quality.py
```

### Resting target placement

- `_submit()` now supports limit prices for both buys and sells.
- A broker-confirmed, single-leg fill places one DAY sell limit at the trade's +75% target.
- The target price is rounded to the actual two-decimal submitted price and stored as `resting_tp_price`.
- Durable fields include `resting_tp_order_id`, `resting_tp_status`, and `resting_tp_submitted_at`.
- Multi-leg spreads are excluded.
- Zero-fill entries are canceled/reconciled and not tracked.
- Partial fills are tracked only for the broker-confirmed filled quantity after canceling the remainder.
- Entries with broker-confirmed quantity but no broker average fill price remain software-managed and do not receive a resting target.

### Resting fill detection

- `_monitor_pass()` refreshes the resting target before fetching the software-exit quote.
- Broker `status=filled` closes durable state using `filled_avg_price`.
- Exit reason is `PROFIT TARGET (resting limit)`.
- P&L source is `broker_filled_avg_price`, not quote midpoint.
- Externally canceled, expired, or rejected targets are retired and software exits remain active.

### Stop/ratchet/time/structural exit sequence

For a single-leg trade with an active resting target:

1. Submit DELETE for the resting order.
2. Poll order status up to three times at one-second intervals.
3. If canceled/terminal, submit the software sell.
4. If filled during cancellation, record the resting fill and do not submit a second sell.
5. If cancellation cannot be confirmed, hold the competing sell and send an alert to prevent an accidental short position.

When the software quote reaches the profit target while the resting order is active, the resting order remains responsible for the fill. The bot does not cancel it merely to send a market order.

### Close-all and kill-switch behavior

- `close_all()` cancels and confirms resting targets before market exits.
- `close_all()` now uses the proper multi-leg close path for spreads.
- The manual-reset kill switch blocks new buys but does not block risk-reducing sells.

## Verification

Host results:

```text
197 Flip-focused tests passed
80 monitor/entry-quality tests passed
Python compilation passed
PowerShell monitor runner parsing passed
Execution gate audit: passed, 100 signals, 0 issues, 1 existing read-only warning
```

New regression cases prove:

- sell limits use the correct DAY limit payload;
- confirmed entry fills place a resting target;
- resting fills stamp the correct exit and broker P&L;
- cancellation is confirmed before a software sell;
- a fill/cancel race cannot double-sell;
- pending software exits remain monitored without duplicate closes;
- the kill switch still blocks buys while allowing protective sells;
- unfilled entries are canceled and do not create phantom open trades;
- partial entries track only broker-confirmed quantity;
- paths without a resting order retain existing behavior.

## Monday Paper Validation

Inspect `C:\Users\kenne\.vibe-trading\flip-trades.json` and Alpaca paper orders for:

- confirmed entry followed by exactly one DAY target order;
- `resting_tp_order_id` matching the broker order;
- target fills recorded from broker `filled_avg_price`;
- stop/ratchet exits showing a canceled resting target before the market sell;
- no duplicate sell orders;
- no resting targets on spreads or entries missing broker average fill price;
- unfilled entry orders canceled without writing open state;
- partial fills recorded with `contracts < requested_contracts`.

## Entry-State Boundary Closed

The legacy estimate-fallback path was removed from durable open-trade creation. After a submitted entry, the bot reconciles broker order status before writing state:

- `filled_qty < 1`: cancel/poll the order, log `entry_not_filled_confirmed`, and do not append a trade.
- partial fill: cancel/poll the remainder, append only the filled integer quantity, and preserve `requested_contracts`.
- broker quantity without broker average fill price: track the real position using the estimate as a defensive software-managed fallback, but mark `entry_price_source=broker_qty_estimate_price`; resting TP remains ineligible.
- broker average fill price: mark `entry_price_source=broker_fill`; resting TP can be submitted for the tracked quantity.

No historical trade records were rewritten.
