# X Trader and Bot Copy Sweep - 2026-07-24

## Scope

- Six X API recent-search requests.
- Fifty posts captured.
- Themes: automated bots, SPY recaps, options execution, 0DTE rules,
  defined-risk premium selling, and bot failures.
- Research only. No order path or existing strategy was changed.
- "Copy" means reproduce a public, mechanical hypothesis and validate it from
  independent market data. It does not mean copy alerts, claimed returns, or
  proprietary code.

Raw reports are stored under
`~/.vibe-trading/reports/x-spy-{automated_bots,spy_trade_recaps,options_execution,zero_dte_rules,defined_risk_premium,bot_failures}-2026-07-24.json`.

## Verdict

No public account supplied enough complete evidence to copy its profitability.
Two public methodologies supplied enough mechanical detail to build independent
shadow challengers:

1. Failed breakdown, reclaim, and acceptance around a predefined level.
2. First-touch SPY rejection at predefined levels with momentum and RSI
   confirmation.

A third family, directional 0DTE credit spreads, is worth a later controlled
test but is not suitable for a $1,000 account without much narrower risk.

## Candidate 1: Failed breakdown and reclaim

### Public rule set

FBDBot describes the following sequence:

1. Select a meaningful structural level.
2. Price flushes below it and attracts breakdown sellers.
3. Price reclaims the level.
4. Wait for acceptance above the level rather than entering on first touch.
5. Execute with fixed stop, target, size, and session controls.

Sources:

- https://x.com/FBDBot/status/2080390537471738136
- https://www.fbdbot.com/learn

The vendor explicitly states that results depend on level quality and user
configuration and does not publish a universal win rate. That honesty improves
methodology credibility but does not prove profitability.

### Existing-system overlap

- Existing MES work has opening levels, session filters, liquidity-sweep ideas,
  and risk controls.
- It does not have a clean, separately scored failed-breakdown/reclaim family.
- Databento one-minute MES data is appropriate for testing the sequence.

### Preregistered challenger: COPY-MES-FBD-01

- Instrument: MES only.
- Data: one-minute, point-in-time Databento trades/bars.
- Levels fixed before entry: prior-day low, overnight low, opening-range low,
  and a predeclared structural shelf definition.
- Long signal:
  - Price trades below the level by the minimum excursion.
  - Price closes back above it within the maximum reclaim window.
  - Acceptance requires the predeclared number of closes without losing it.
  - Enter on the next executable price.
- Short failed-breakout version must be scored separately.
- Stop: beyond the flush extreme plus one slippage allowance.
- Targets: fixed 1.5R and 2R variants only.
- Limits: one trade per direction per level, session cutoff, and daily loss cap.
- Costs: commissions plus baseline, double, and stressed slippage.

Promotion requires untouched walk-forward performance and 30 forward-shadow
trades. The level definition must not be optimized on the final period.

## Candidate 2: SPY first-touch rejection

### Public rule set

The clearest public version uses:

- Trade window approximately 9:30-11:15 ET.
- Predefined whole-dollar, previous-day high/low, and premarket levels.
- First touch only.
- Fast approach into the level.
- One-minute RSI extreme.
- Immediate bracket order.
- One loss requires a break; no averaging, chasing, or moving the stop.

Sources:

- https://x.com/shentrades/status/2080021529136660915
- https://www.spy0dte.com/hub
- https://shentrades.substack.com/p/748-is-the-only-level-that-matters

The public material proposes a 20% target and 12.5% premium stop, but provides
no audited distribution of all trades. Those exits are challenger parameters,
not facts.

### Existing-system overlap

- The Flip bot already blocks weak same-direction reentries, limits account
  risk, and records 0DTE shadow candidates.
- Prior-day and opening-range context already exists in parts of the stack.
- First-touch status, approach speed, and the exact level-rejection sequence are
  not one isolated challenger today.

### Preregistered challenger: COPY-SPY-FT-01

- Underlying signal tested before option selection.
- Levels fixed before the session: PDH, PDL, PMH, PML, and whole-dollar levels.
- Window: 9:30-11:15 ET.
- Signal:
  - First touch of the level that session.
  - Approach-speed bucket computed without future bars.
  - One-minute RSI in one of two predeclared extreme bands.
  - Rejection close away from the level.
- Calls and puts scored separately.
- First pass exits on the underlying use fixed R multiples.
- Option replay is permitted only after obtaining point-in-time minute NBBO,
  Greeks, and contract selection data.
- Socially proposed 20% target / 12.5% stop is tested as one fixed variant, not
  optimized until attractive.

## Candidate 3: Directional 0DTE credit spreads

Several recent posts showed timestamped SPX call credit spreads reaching 50% of
maximum profit:

- https://x.com/FPL_Trading/status/2080772230213234955
- https://x.com/FPL_Trading/status/2080393269130023375
- https://x.com/FPL_Trading/status/2080119564604420309

The visible sequence contains winners but does not expose all attempted trades,
losses, fill quality, or selection rules. It therefore fails replication.

An independent Reddit post claims 288 trades, a 78.1% win rate, $140.85 average
winner, $325.46 average loser, and $1,403 maximum drawdown:

- https://www.reddit.com/r/GEXOptionsTrading/comments/1v4uzoi/my_18month_spx_0dte_credit_spread_results_288/

Those are self-reported results. The payoff shape also shows why win rate is
misleading: the claimed average loss is more than twice the average winner.

Cboe confirms that limited-risk spreads are common in 0DTE trading, while also
noting that an out-of-the-money credit spread's potential profit is smaller
than its potential loss:

- https://www.cboe.com/tradable-products/0dte
- https://www.cboe.com/insights/posts/0-dt-es-decoded-positioning-trends-and-market-impact

### Decision

- Do not deploy SPX five-point spreads on a $1,000 account.
- A near-maximum loss can consume roughly half the account before credit.
- Preserve this only as a future XSP/SPY narrow-width paper experiment with
  complete NBBO and assignment-aware simulation.
- Gamma commentary cannot be treated as a causal input by itself. Cboe research
  finds aggregate 0DTE market-maker hedging small relative to S&P futures
  liquidity:
  https://www.cboe.com/insights/posts/volatility-insights-evaluating-the-market-impact-of-spx-0-dte-options

## Rejected patterns

- Dollar or percentage screenshots without quantity and complete fills.
- "Live alerts" that reveal only winners.
- Claims that a bot is always watching SPY without rules or outcomes.
- Averaging into 0DTE puts.
- Short straddles without defined risk.
- Any fixed daily-income claim.
- Gross option volume interpreted as directional pressure without signed flow.

## Build order

1. Implement COPY-MES-FBD-01 as a separate Databento replay and shadow family.
2. Implement COPY-SPY-FT-01 as an underlying-only replay.
3. Audit timestamp construction, level look-ahead, same-bar ambiguity, and
   slippage adversarially.
4. Test options execution only after minute NBBO data is available.
5. Leave the credit-spread family quarantined until account-size and data gates
   are satisfied.

## Confidence

- Failed-breakdown hypothesis deserves testing: 8/10.
- SPY first-touch hypothesis deserves testing: 7/10.
- Public credit-spread profitability claim: 3/10.
- Ability to copy any public account's profitability today: 1/10.
- Live-capital readiness of these challengers: 0/10.
