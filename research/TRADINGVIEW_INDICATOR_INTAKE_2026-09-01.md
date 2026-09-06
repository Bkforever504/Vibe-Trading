# TradingView Indicator Intake: ROOK, GCGrid, Trader Assistant Pro

Date: 2026-09-01  
Scope: assess the three supplied TradingView indicators as *decision-support
inputs*, not as evidence of a profitable strategy or as execution authority.

## Bottom line

Only **GCGrid** is open-source, but it is intentionally a gold-specific
psychological-level map, not a trade signal. **ROOK** and **Trader Assistant
Pro** disclose useful high-level mechanics but their exact source and
parameters are unavailable.  None should be copied into the A+/B+ rank,
trigger an order, or be treated as validated performance.

The useful permanent additions are conceptual and already substantially overlap
with Vibe-Trading: a point-in-time level lifecycle (probe/reclaim vs
acceptance), confirmed-close-only alerts, visible entry/stop/target lifecycle,
and executable-quote checks.  Any new implementation must be an independently
specified shadow experiment with point-in-time bars and option NBBO validation.

## 1. ROOK — level lifecycle / sweep context

Official page: [ROOK — TradingView](https://www.tradingview.com/script/OXOltkHy-ROOK/)

### What is reproducible from the published description

- It maps current-timeframe pivots; up to three higher-timeframe pivot layers;
  prior regular-session and overnight highs/lows; and optional round numbers.
- Nearby levels are merged into a pool with a touch count. A pool transitions
  `resting → in contention → swept` when price enters its far-side band and
  closes back through the level, or `accepted` when price closes beyond and
  remains there. A later acceptance invalidates a prior sweep.
- Its stated alerts are buy-side sweep, sell-side sweep, acceptance above,
  acceptance below, and an optional top-grade-only sweep alert.
- Pivot and higher-timeframe timing is explicitly delayed: pivots exist only
  after confirmation, higher-timeframe data is requested without lookahead and
  becomes usable after the higher-timeframe bar closes, and close-dependent
  transitions are evaluated at bar close.

### Important constraint

ROOK is a **protected, closed-source** indicator. The 0–100/letter sweep grade
is explicitly calculated after a future measuring window, so it is
retrospective and must never be used as a real-time entry grade. The page calls
the tool visual planning support, not a strategy; it neither backtests nor
places trades. Its page does not publish a webhook payload contract.

### Vibe-Trading overlap and disposition

- Existing `scripts/liquidity_sweep_scanner.py` already records a
  point-in-time `failed_breakout_wick_reclaim` proxy using overnight levels,
  range/volume constraints, and confirmation bars.
- `scripts/intraday_opportunity_radar.py` already observes
  `sweep_and_reclaim`, `sweep_and_reject`, VWAP reclaim/reject, opening-range
  geometry, liquidity and spread gates.
- The missing exact ROOK elements are *multi-timeframe pooled levels* and a
  clean **acceptance-after-sweep invalidation** state. These are research
  candidates, not an A+/B+ upgrade until independently forward tested.

**Use:** optionally ingest a user-owned ROOK alert as a non-authoritative
external context event, then cross-check it with our own bars and levels. Do
not ingest its after-the-fact grade and do not make it an execution gate.

## 2. GCGrid Psych Levels — deterministic gold context

Official page: [GCGrid Psych Levels — TradingView](https://www.tradingview.com/script/ZIQRZaiD-GCGrid-Psych-Levels-NomadaScalper/)

### Public mechanics

- The code is listed as **open source** on TradingView (subject to its House
  Rules). The published definition is deliberately simple: gold zones at every
  absolute $100 and $250; multiples of $500 are confluent; each zone has a
  configurable half-width band.
- A confirmed-bar arrival marker records possible support when the prior close
  was above a zone and the current bar reaches it, or possible resistance for
  the inverse. A level rearms only after price moves more than half a grid step
  away.
- Markers record an arrival, not a reversal result; the author states that the
  tool has no buy/sell signals and publishes no win rate. The optional FastZone
  is only a visual midpoint between $100 levels.

### Constraint and disposition

The absolute $100/$250 constants are designed expressly for gold's price range
and are intentionally not editable. Therefore they must **not** be imported as
SPY/SPX/QQQ or equity-option levels. A future configurable psychological-zone
module could be built for each instrument only after a separate fixed-rule
study; it would be context, never a trigger.

## 3. Trader Assistant Pro — disclosed workflow, non-reproducible product

Official page: [Trader Assistant Pro — TradingView](https://www.tradingview.com/script/ZoccxbOB-Trader-Assistant-Pro-WillyAlgoTrader/)  
Author manual: [Trader Assistant Pro guide](https://willyalgotrader.pro/strategy/manual/)

### Published workflow

The product describes: swing detection → staged 1-2-3 pattern → 0–100 quality
score → trend/structure filters → five-factor confluence → Fibonacci OTE entry
zone, stop and three targets → reversal-candle confirmation in the zone on a
confirmed close → trailing stop and outcome tracking.

The disclosed geometry is entry at the 0.5 retracement of the 1–2 wave, stop
at the 0.886 retracement, and three Fibonacci extensions. Its five published
confluence factors are score, direction of its trend bands, higher-timeframe
trend, nearby same-direction FVG, and Stage 3 confirmation. Trend Bands use a
KAMA (efficiency window 21; fast 2; slow 34) with ATR(14) × 0.618 bands.

### Evidence and alert constraints

- This is an **invite-only** product; access requires author approval and the
  source and exact presets are not auditable.
- The author says preset optimization used a one-year 15-minute in-sample
  period and excludes fees/funding; breakeven outcomes are counted favorably.
  It is not independent out-of-sample evidence.
- Alerts fire on confirmed-bar close. Full Entry/SL/TP/score/confluence JSON is
  only offered through TradingView's `Any alert() function call`; named
  alertconditions expose only ticker/price placeholders. The listing says it
  can emit armed, confirmed, stop-moved, stop-hit, and TP events.

### Vibe-Trading overlap and disposition

- `scripts/contextual_pattern_observation.py` already observes 4H-to-15m FVG
  context, completed bars, and requires a subsequent lower-timeframe reaction;
  it is correctly non-executable.
- `scripts/intraday_trade_lifecycle_shadow.py` already emits a frozen shadow
  lifecycle with entry, initial stop, 1R, 2R, time stop, and an explicit manual
  decision contract.
- Existing option-liquidity and feasibility components are stricter than this
  chart-only product for actual execution because they require quote freshness,
  spread and liquidity evidence.

**Use:** do not reproduce unpublished presets or treat the vendor's score as
our A+/B+. If the user separately purchases and configures it, accept a
webhook only as an external candidate. Verify timestamp, symbol, direction,
levels, bar-close status, fresh underlying quote, executable option NBBO,
portfolio exposure and daily loss limit before it may appear as a manually
reviewable candidate. It cannot place trades or bypass the existing decision
contract.

## Permanent intake rules

1. A third-party alert is a **candidate**, not an A+/B+ rating or trade.
2. Every candidate must be reproducible from timestamped market data, without
   future-grade fields or repainting/confirmed-pivot ambiguity.
3. It must have fixed entry, invalidation, targets/time exit and a defined
   instrument-specific cost/quote model before evaluation.
4. Independent forward/OOS evidence is required before promotion; vendor
   backtests, screenshots and optimized presets are insufficient.
5. An actual manual action remains subject to fresh quote/spread, contract
   liquidity, portfolio correlation and daily-risk checks at that moment.

## Sources

- [ROOK official TradingView listing](https://www.tradingview.com/script/OXOltkHy-ROOK/)
  (published mechanics, source/access status, timing and alerts).
- [GCGrid official TradingView listing](https://www.tradingview.com/script/ZIQRZaiD-GCGrid-Psych-Levels-NomadaScalper/)
  (open-source status, fixed grid mechanics and stated scope).
- [Trader Assistant Pro official TradingView listing](https://www.tradingview.com/script/ZoccxbOB-Trader-Assistant-Pro-WillyAlgoTrader/)
  (workflow, formula disclosures, in-sample caveat and alert semantics).
- [Trader Assistant Pro author guide](https://willyalgotrader.pro/strategy/manual/)
  (author's detailed alert limitation and workflow description).
