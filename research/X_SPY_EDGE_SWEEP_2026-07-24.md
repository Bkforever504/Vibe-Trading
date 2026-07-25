# X SPY Edge Sweep - 2026-07-24

## Scope and controls

- Source: X API v2 recent search.
- Queries: 0DTE execution, dealer gamma, volume/order flow, repeatable intraday levels, and risk postmortems.
- API use: five requests, at most ten recent posts per request.
- Captured: 47 posts.
- Purpose: hypothesis generation only. No post is execution-eligible.
- Safety: no trading rules, risk limits, or orders were changed.

The raw point-in-time reports are stored under
`~/.vibe-trading/reports/x-spy-*-2026-07-24.json`. The request attempts are
recorded in `~/.vibe-trading/x-api-request-budget.json`.

## Evidence quality

Most of the sample was not suitable as trading evidence:

- Promotional or community pitches.
- Outcome screenshots without complete entry, exit, size, and losing-day data.
- Duplicate posts.
- Hindsight commentary with no timestamped invalidation.
- False-positive text matches for the ordinary words "spy" and "orb".

Posts that contained a measurable idea were still treated as unverified.
Follower counts and engagement were not used as evidence of an edge.

## Repeated, testable ideas

### 1. Gamma as a regime filter

Several posts independently described price behavior around a gamma flip or
large gamma level. The useful hypothesis is not "follow a gamma account." It is:

- Long-gamma sessions should favor pinning, failed breakouts, and mean reversion.
- Short-gamma sessions should favor range expansion and momentum continuation.
- A change through the gamma flip may change which model is eligible.

Examples:

- https://x.com/GreeksOptions/status/2080714705539055965
- https://x.com/GreeksOptions/status/2080745014976536720
- https://x.com/DynamicTrendInc/status/2080754655798214909

This requires an independent, timestamped gamma dataset. X commentary cannot
serve as the input.

### 2. Level plus confirmation, not level alone

The repeatable structure was a known level followed by a hold, rejection, or
reclaim:

- Five-minute opening range high or low.
- Premarket high or low.
- Previous-day high or low.
- VWAP or a short intraday EMA as confirmation.

Examples:

- https://x.com/astrotraderr/status/2080666748790206852
- https://x.com/Paulie_D00/status/2080693006936768995
- https://x.com/OptionCookie/status/2080686383551910034

This overlaps the existing ORB work, but suggests testing rejection and retest
families separately instead of adding more conditions to one ORB model.

### 3. Breadth and leadership divergence

Posts noted cases where cap-weighted SPY was flat while equal-weight or sectors
moved materially, and cases where index gamma differed from large-component
gamma. The testable claim is that breadth and leadership agreement may improve
directional SPY entries; disagreement may be a no-trade or mean-reversion
condition.

Examples:

- https://x.com/TradeApologist/status/2080746895329112344
- https://x.com/MonacoMacro/status/2080813504081043530

### 4. Flow needs multiple confirmations

One post exposed a concrete candidate stack: unusually high volume/open
interest, clustered prints, sweeps, dark-pool activity near the strike, and a
nearby options wall. That is testable only with point-in-time OPRA and dark-pool
data. It must not be approximated from social posts.

Example:

- https://x.com/saadjamal_/status/2080742576424902826

### 5. Loss handling may matter more than another entry indicator

The useful risk hypothesis is to stop after a failed attempt unless a fresh,
fully independent setup forms. The sample also contained a public 0DTE signal
system reporting only 27.8% accuracy, a useful warning against optimizing for
activity.

Examples:

- https://x.com/ShaddyTrades/status/2080729308192993380
- https://x.com/isalles_trades/status/2080748605900501278

## Preregistered experiments

These are separate challengers. They must not be combined until each has enough
independent evidence.

### XSPY-01: Gamma-conditioned ORB

- Base: current frozen five-minute SPY ORB definition.
- Challenger: use gamma sign only to select breakout versus rejection model.
- Primary metric: expectancy after spread, slippage, and option execution costs.
- Secondary metrics: profit factor, max drawdown, trade count, and worst decile.
- Failure: no improvement out of sample, dependence on one month, or top 1% of
  trades supplies more than half of profit.

### XSPY-02: Level-retest continuation

- Entry: first retest after a close beyond ORB, premarket, or previous-day level.
- Confirmation: price on the correct side of VWAP and five-minute relative
  volume above the preregistered threshold.
- Invalidation: underlying closes back through the level.
- Test calls and puts separately.

### XSPY-03: Breadth-confirmed direction

- Inputs: SPY, RSP, QQQ, sector ETF returns, advance/decline breadth where
  available.
- Challenger: directional entries only when index and breadth agree.
- Alternate challenger: fade the index when cap-weighted and equal-weight
  direction materially diverge.
- Do not choose between them on the final test period.

### XSPY-04: One-reentry risk policy

- Compare zero reentries, one fresh-setup reentry, and unrestricted baseline.
- Daily risk remains fixed across variants.
- A reentry requires a new signal timestamp and renewed confirmation; it cannot
  be a larger version of the stopped trade.

## Promotion gates

No challenger can influence Alpaca orders until it passes all of the following:

1. Point-in-time inputs with no social-post dependency.
2. Train, selection, and untouched final periods.
3. Positive expectancy under at least double estimated execution costs.
4. No single regime or top 1% of trades dominates the result.
5. At least 30 resolved forward-shadow trades.
6. Adversarial lifecycle and look-ahead audit.

## Current confidence

- Confidence that X produced useful hypotheses: 7/10.
- Confidence that any sampled claim is a live edge: 2/10.
- Confidence that the four experiments are worth controlled testing: 7/10.
- Confidence for live-capital use: 0/10 until the promotion gates pass.
