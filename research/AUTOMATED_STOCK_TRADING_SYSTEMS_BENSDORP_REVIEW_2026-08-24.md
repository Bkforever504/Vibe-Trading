# Laurens Bensdorp and Systematic Stock-Trading Books: Dashboard Intake Review

Date: 2026-08-24  
Decision: useful architecture; exact systems remain external shadow hypotheses  
Execution authority: none

## Executive verdict

Laurens Bensdorp's *Automated Stock Trading Systems* can help this project, but
its highest-value idea is the portfolio construction: combine independently
defined long momentum, long mean-reversion, short mean-reversion, and defensive
sleeves whose losses should not occur at the same time. It is not credible
evidence that the dashboard can inherit a 40% CAGR by copying three rules.

The visible book allocation is 50% Long Trend High Momentum, 50% Long Mean
Reversion Selloff, and 100% Short RSI Thrust. That is as much as 100% long plus
100% short, or roughly 200% gross exposure. The reported 39.59% CAGR and about
19.3% maximum drawdown for 1995-2019 are therefore not an apples-to-apples
comparison with an unlevered S&P 500 position.

No first-party, independently checkable out-of-sample record was found for the
unchanged three-system portfolio after the book's 2019 cutoff. Later author
posts describe different or expanded simulations. The original performance
remains a hypothetical backtest without a public trade ledger, frozen version,
daily return series, or third-party audit.

## What is actually in the book

The social post understates the scope. The licensed contents preview lists
seven systems:

1. Long Trend High Momentum
2. Short RSI Thrust
3. Long Mean Reversion Selloff
4. Long Trend Low Volatility
5. Long Mean Reversion High ADX Reversal
6. Short Mean Reversion High Six-Day Surge
7. Catastrophe Hedge

Publisher and catalog records describe simulated results over roughly 24 years,
not audited live performance. The precise rules should be transcribed and
hashed only from a legally purchased copy; public summaries omit implementation
details such as indicator conventions, tie-breaking, corporate actions, and
same-bar order priority.

Primary/catalog sources:

- [Lioncrest official book page](https://lioncrest.com/books/automated-stock-trading-systems-laurens-bensdorp)
- [Apple Books edition](https://books.apple.com/us/book/automated-stock-trading-systems/id1499644467)
- [Licensed Everand contents preview](https://www.everand.com/book/455867779/Automated-Stock-Trading-Systems-A-Systematic-Approach-for-Traders-to-Make-Money-in-Bull-Bear-and-Sideways)

## Evidence audit

The author's stated backtest assumptions are better than many retail-system
claims: listed and delisted stocks, split adjustment, commissions, slippage,
margin interest, liquidity filters, and position limits are discussed. However,
the publicly available material does not make the following independently
reproducible:

- exact point-in-time universe membership and data vendor;
- numerical slippage model;
- borrow availability, locate fees, recalls, and hard-to-borrow exclusions;
- complete corporate-action and delisting-return treatment;
- exact daily returns, trade ledger, source code, or third-party audit.

This matters most for the short sleeve and the 1995-2019 broad-stock universe.
Current proxy OHLCV data cannot establish a survivorship-bias-free replication.
Norgate documents that delisted securities and historical index constituents
are subscription features intended for point-in-time testing:

- [Norgate data contents](https://norgatedata.com/data-content-tables.php)
- [Norgate data FAQ](https://norgatedata.com/data-package-faq.php)

The author has published later simulations, but they do not validate the exact
book portfolio. A 2022 post used five systems and reported 27% CAGR and 11.7%
maximum drawdown since 2003. A 2024 post used a different Nasdaq-100 long/short
combination and reported 43.7% CAGR with 42% maximum drawdown. Current workshop
materials present still other figures without a reproducible frozen portfolio:

- [Bensdorp 2022 five-system simulation](https://x.com/laurensbensdorp/status/1538928442120470529)
- [Bensdorp 2024 Nasdaq-100 simulation](https://x.com/laurensbensdorp/status/1759370767735611555)
- [Current official workshop claim](https://www.tradingsystems.com/workshop63952894)

The correct status is therefore `external_hypothesis`, not `verified_edge`.

## What the broader literature supports

The component ideas have respectable empirical foundations, but that evidence
does not verify Bensdorp's parameters or headline return.

- Medium-horizon cross-sectional momentum has longstanding evidence in
  [Jegadeesh and Titman (1993)](https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.1993.tb04702.x).
- Time-series trend persistence across liquid futures is documented by
  [Moskowitz, Ooi, and Pedersen](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2089463).
- Short-run reversal can survive transaction costs under carefully controlled
  liquidity and turnover conditions in
  [de Groot, Huij, and Zhou](https://repub.eur.nl/pub/25718).
- Published anomalies often decay: McLean and Pontiff report lower returns out
  of sample and after publication across 97 predictors
  ([Journal of Finance](https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12365)).
- Multiple strategy searches require explicit overfitting controls such as the
  [Probability of Backtest Overfitting](https://escholarship.org/uc/item/4w1110bb).

## Comparison with the existing Vibe-Trading stack

### Already covered

- Momentum: the repository already has a preregistered three-sleeve momentum
  ensemble and a canonical 12-month cross-asset rotation candidate. Its
  2015-2024 report shows 123 trades, profit factor 1.53, out-of-sample profit
  factor 1.78, Sharpe 0.49, and 24.3% maximum drawdown. This is more useful than
  adding a loosely specified duplicate momentum rule.
- Mean reversion: the QQQ Double-7 and RSI(2) work already includes costs,
  sealed windows, drawdown analysis, and multiple-testing correction. Neither
  variant passed the experiment-wide threshold, so both correctly remain
  shadow challengers.
- Governance: preregistration, family ledgers, BH-FDR, PBO, regime minima,
  outcome resolution, and execution-disabled gates already exceed what can be
  inferred from the book's public evidence.

### Incremental gaps worth closing

1. A cross-strategy sleeve allocator covering all resolved ledgers, not only
   options outcomes.
2. Rolling correlation and worst-joint-loss analysis across momentum,
   mean-reversion, ORB, MES, options, and short-reversal families.
3. Marginal contribution metrics: expectancy, drawdown, tail loss, turnover,
   and regime coverage before and after adding a sleeve.
4. Gross/net exposure, symbol overlap, time overlap, capacity, and cost stress.
5. A catastrophe/defensive sleeve research family, kept separate from signal
   grading and evaluated for portfolio protection rather than standalone CAGR.
6. A point-in-time historical equity-data route before broad-universe or short
   system evidence can count toward promotion.

The existing `scripts/clustered_portfolio_monte_carlo.py` is a useful starting
point, but it consumes an options shadow ledger and measures correlations only
on overlapping resolution days. It does not yet provide a whole-system sleeve
allocator or mark-to-market correlation.

## Recommended author and book priority

| Priority | Author / book | Best use here | Decision |
| --- | --- | --- | --- |
| 1 | Robert Carver, *Systematic Trading* | Portfolio allocation, diversification, sizing, turnover, uncertainty | Highest incremental value; adapt to the dashboard |
| 2 | David Aronson, *Evidence-Based Technical Analysis* | Scientific testing of technical rules and data-mining controls | Audit current governance; do not create duplicate machinery |
| 3 | López de Prado and Bailey et al. | Purged validation, leakage and overfitting controls | Extend validation only where current tests show a gap |
| 4 | Andreas Clenow, *Stocks on the Move* | Equity momentum universe, ranking, regime and sizing | Benchmark against the existing momentum sleeve |
| 5 | Cesar Alvarez / Larry Connors | Liquid-equity mean-reversion challengers | Preregister a small number; expect publication decay |
| 6 | Ernest Chan, *Algorithmic Trading* | Cointegration and portfolio mean reversion | Useful later for pairs/stat-arb with point-in-time data |
| 7 | Perry Kaufman, *Trading Systems and Methods* | Broad reference library and candidate generation | Research source only, never direct promotion |
| 8 | Laurens Bensdorp | Multi-system architecture and seven candidate families | Test the architecture; distrust the headline |

Official resources:

- [Robert Carver's systematic-trading resources and open-source code](https://www.systematicmoney.org/systematic-trading-resources)
- [David Aronson, Evidence-Based Technical Analysis](https://www.wiley.com/en-us/Evidence-Based+Technical+Analysis%3A+Applying+the+Scientific+Method+and+Statistical+Inference+to+Trading+Signals-p-9780470008744)
- [Marcos López de Prado, Advances in Financial Machine Learning](https://www.wiley.com/en-us/Advances+in+Financial+Machine+Learning-p-9781119482086)
- [Andreas Clenow, Stocks on the Move](https://www.followingthetrend.com/2015/06/stocks-on-the-move-is-out/)
- [Ernest Chan, Algorithmic Trading](https://onlinelibrary.wiley.com/doi/book/10.1002/9781118676998)
- [Perry Kaufman, Trading Systems and Methods](https://onlinelibrary.wiley.com/doi/book/10.1002/9781119202561)
- [Cesar Alvarez on optimization decay](https://alvarezquanttrading.com/blog/optimization-mean-reversion/)

## Proposed dashboard intake

The safest and most valuable implementation is a read-only **Strategy Portfolio**
panel built from already-resolved shadow outcomes:

- sleeve cards for momentum, long mean reversion, short mean reversion, ORB,
  futures, options, and defensive overlays;
- rolling 20/60/120-session correlation and overlap matrix;
- marginal expectancy and marginal maximum-drawdown contribution;
- gross exposure, net exposure, concentration, turnover, cost stress, and
  capacity warnings;
- regime performance and minimum-evidence status per sleeve;
- worst simultaneous loss and clustered-bootstrap risk;
- `ADD`, `HOLD`, or `REJECT` as research decisions only;
- provenance, freshness, spec hash, universe hash, and evidence tier on every
  surface;
- `execution_enabled=false` and `can_submit_orders=false` hardcoded.

For Bensdorp specifically:

1. Purchase/borrow the legal book and transcribe the seven exact specifications.
2. Hash and preregister each system as a separate external family.
3. Map Long Trend High Momentum against the current momentum incumbent rather
   than treating it as a new independent edge.
4. Map Long Mean Reversion Selloff against the existing QQQ mean-reversion
   family and a liquid-equity challenger.
5. Keep Short RSI Thrust promotion-ineligible until point-in-time borrow,
   locate-fee, and short-sale-constraint data are modeled.
6. Evaluate the combined portfolio only after each sleeve has independent
   forward evidence; use realistic financing and cap gross exposure.
7. Preserve every failure and apply the existing family-wise/FDR gates.

## Final decision

Do not implement the book's claims directly into A+ ranking. Add the portfolio
diversification layer first, because it extracts the book's real insight from
evidence the system already collects. Then admit the seven systems as frozen,
shadow-only challengers after exact legal transcription and point-in-time data
are available.

No execution setting, live bot, order authority, or data ledger was changed by
this review.
