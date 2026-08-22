# Milkman Strategy Suite Preregistration

Date: 2026-08-14

## Authority

This suite is research and shadow observation only. It cannot submit orders,
change production gates, change sizing, or promote itself. No strategy in this
document is accepted as profitable based on the publisher's results.

## Sources

1. Weekly SPX -1 ATR put spread:
   https://milkmantrades.com/atr-premium-selling.html
2. Daily Bilbo compression breakout:
   https://milkmantrades.com/bilbo-daily.html
3. Bilbo Box Options v2:
   https://milkmantrades.com/bilbo-box-options-v2.html
4. Swing Golden Gate short:
   https://milkmantrades.com/swing-gg-stocks.html
5. 0DTE Pin Convergence catalog entry:
   https://milkmantrades.com/#strategies

## Frozen Implementations

### 1. Weekly SPX -1 ATR put spread

- First trading day of the week at 10:00 ET.
- Short strike is prior completed weekly close minus prior completed weekly
  Wilder ATR(14), rounded half-up to the nearest five points.
- Long strike is 50 points below the short strike.
- Current-week SPXW expiry; hold to cash settlement.
- Candidate exists only when the point-in-time short bid minus long ask is
  positive.
- A global minimum credit-to-risk threshold is not applied. This strategy must
  be judged on its own loss frequency, loss severity, and executable credit.

The existing underlying audit remains
`research/spx_weekly_atr_put_spread_lab.py`. It cannot establish option P&L.

### 2. Daily Bilbo equity breakout

- Compression state must come from a verified Saty Phase Oscillator series.
  This suite does not guess proprietary/default compression parameters.
- Box is the high and low of the first five compression sessions, or all
  available compression sessions when an episode ends earlier.
- The resting buy stop can be active only after the box-locking close.
- It works for 20 trading sessions, requires the prior close above the prior
  daily EMA21, and is canceled if the box low trades first.
- If the box high and low both trade in a daily bar, the replay cancels the
  entry because intraday ordering is unknown.
- Initial stop is box low. The stop ratchets to the prior daily EMA50 and never
  moves down. The optional scr3 exit closes when one of the first three closes
  returns inside the box.

### 3. Bilbo Box Options v2

- Uses the verified hourly compression box and a confirmed hourly close above
  box high. No intrabar confirmation is permitted.
- Signal volume must equal or exceed the median volume for the same clock hour
  over the prior 20 sessions.
- Prior daily close must be above prior daily EMA21.
- Expiry is nearest to 28 DTE within 21-37 DTE.
- Strike is nearest to spot plus 0.75 times daily ATR(14).
- Quote must be live, two-sided, and no wider than 5% of midpoint.
- Modeled entry is halfway from midpoint to ask. This remains a benchmark, not
  proof of fillability.
- Exit on a five-minute underlying close below box low; after a +1 ATR move,
  exit after giving back 75% of peak underlying gain; otherwise exit after ten
  trading days.

The source's 4% premium sizing is recorded but not accepted. Research risk is
capped at 2% before any portfolio simulation, with lower 0.5% and 1% arms to be
tested.

### 4. Swing Golden Gate short

- Monthly levels use prior completed month close and prior completed monthly
  Wilder ATR(14).
- Gate opens at -0.382 ATR while the previous close is above daily EMA21.
- Resting short entry is -0.618 ATR, target -1.0 ATR, stop the monthly pivot,
  and remaining exposure closes at month end.
- Gap entry fills at the opening price when it is worse than the stop level.
- Same-bar stop/target ambiguity is resolved stop first.
- Correlated signals share one risk budget.

The publisher reports a conflicting broker-bar reconstruction near zero
expectancy. Independent reproduction must resolve that conflict.

### 5. 0DTE Pin Convergence

The publisher marks this strategy "coming soon" and supplies no deterministic
rules. The implementation therefore always returns a specification blocker.
Context fields may be recorded, but no thresholds, structures, or exits are
inferred.

## Evidence Gates

No candidate can change production behavior until all applicable gates pass:

- Exact point-in-time inputs and source timestamps are retained.
- Natural or marketable bid/ask execution remains positive after commissions.
- At least 100 resolved trades and 50 independent signal dates, except the
  weekly SPX candidate, which requires at least 52 forward weeks.
- Development, selection, and untouched final windows are positive.
- Day-clustered bootstrap confidence interval and Deflated Sharpe are reported.
- Leave-one-year-out and leave-one-symbol-out results do not reveal a single
  point of failure.
- Expectancy remains positive after removing the top 1% and top 5% of winners.
- Concurrency-aware portfolio drawdown and expected shortfall pass the risk
  budget.
- Independent Codex and Claude review agrees that the evidence is reproducible.

## Non-Goals

- No scheduler registration.
- No broker adapter.
- No live or paper order submission.
- No edits to Flip Bot, IWM Bot, theta harvester, or global risk settings.
- No claim that a published backtest is an independently verified edge.
