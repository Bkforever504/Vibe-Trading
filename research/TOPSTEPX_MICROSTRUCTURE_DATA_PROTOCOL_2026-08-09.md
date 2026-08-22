# TopstepX MES Microstructure Data Protocol - 2026-08-09

## Purpose

The one-minute MES research inventory has not produced a strategy that passes
current-regime selection and realistic costs. The next research lane therefore
adds genuinely new information rather than another candle transformation:

- best bid/ask quotes;
- aggressor-classified trades; and
- explicit depth-of-market updates.

ProjectX documents all three streams on its market SignalR hub. Topstep states
that TopstepX uses the exchange feed and an explicit, rather than synthetic,
book. Sources:

- https://gateway.docs.projectx.com/docs/realtime/
- https://help.topstep.com/en/articles/14434175-topstepx
- https://help.topstep.com/en/articles/11187768-topstepx-api-access

## Safety Boundary

- Recorder mode is read-only.
- `execution_enabled` and `can_submit_orders` are always false.
- The recorder contains no account, position, or order methods.
- It only accepts contract IDs beginning with `CON.F.US.MES.`.
- Files rotate at 50 MB with three backups.
- The local runner requires `PERSONAL_DEVICE_CONFIRMED` because Topstep
  prohibits API use from VPS, VPN, and remote-server environments.
- No scheduler is installed automatically.

## Raw Evidence

`strategies/topstepx_market_recorder.py` stores normalized JSONL rows with:

- event type and contract ID;
- exchange/source timestamp when supplied;
- local UTC receipt timestamp; and
- the unchanged quote, trade, or depth payload.

The dual timestamps permit a latency and ordering audit. Raw data remains the
source of truth; derived features can always be rebuilt.

## Derived Windows

`research/topstepx_microstructure_features.py` produces causal five-second
windows containing:

- average spread in MES ticks;
- signed aggressive volume and aggressor imbalance;
- quote-mid response in ticks;
- top-five bid and ask depth; and
- top-five depth imbalance.

These are continuous measurements, not entries. No absorption or continuation
threshold is frozen until the collection gate below passes.

## Collection Gate

Before hypothesis selection:

- at least 20 complete RTH sessions;
- at least 50,000 quote events, 50,000 trade events, and 50,000 depth events;
- at least 95% of active five-second windows contain all three event types;
- p99 local receipt minus source timestamp below 1 second;
- no unresolved reconnect gap longer than 10 seconds during 09:30-11:30 ET;
- contract ID and tick specification verified daily; and
- event-day labels recorded before analysis.

If the gate fails, fix collection first. Do not tune a trading strategy on
partial market-depth data.

## First Frozen Tests After Collection

Only after the gate passes, preregister a small family around:

1. aggressive-volume pressure with weak same-direction mid-price response
   (absorption/reversal candidate);
2. pressure aligned with persistent depth imbalance and price response
   (continuation candidate); and
3. spread widening or book depletion as an execution block, not a direction
   prediction.

Use chronological walk-forward evaluation, doubled costs, one-update delay,
session-level block bootstrap, and exact Topstep Combine scoring. The first 20
sessions are development-only. Subsequent promotion evidence must be collected
forward after parameters and code hashes are frozen.
