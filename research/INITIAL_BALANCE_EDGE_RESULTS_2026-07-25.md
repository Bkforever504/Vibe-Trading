# Initial Balance / Opening Range Results - 2026-07-25

## Verdict

No tested Initial Balance or 15-minute opening-range rule earned promotion,
shadow scheduling, or access to an execution gate.

The broad public statistic is real: one or both sides of a 60-minute Initial
Balance are breached on almost every complete session. That is not a trading
edge by itself. Once entry timing, stop order, path, and costs are enforced,
the tested rules are negative or statistically indistinguishable from zero.

## Data and controls

- MES: 1,148 raw sessions; 1,108 complete one-minute RTH sessions accepted.
- SPY: 1,137 raw IEX sessions; only 411 complete one-minute sessions accepted.
- NQ/MNQ proxy: all 48 five-minute sessions complete; diagnostic only.
- Start-labeled 16:00 bars excluded; incomplete sessions fail closed.
- Four frozen strategies across 15- and 60-minute ranges.
- One trade maximum per strategy per session; next-bar entries only.
- Stop-first same-bar ambiguity.
- MES/MNQ commission and two-sided slippage; SPY one basis point per side.
- Target-hit and positive-EOD-return rates reported separately.
- Gross expectancy, cost in R, timestamp, source hashes, and cost specs saved.
- 2,000-sample five-trade moving-block intervals, plus familywise intervals
  adjusted for eight fixed tests.
- No parameter sweep and no option-return inference.

Machine-readable report: `data/initial_balance_edge_results.json`

## Descriptive validation

### 60-minute IB

| Market | Complete sessions | Any wick break | Single | Double | None |
|---|---:|---:|---:|---:|---:|
| MES | 1,108 | 98.01% | 69.86% | 28.15% | 1.99% |
| SPY IEX | 411 | 97.32% | 68.86% | 28.47% | 2.68% |
| NQ proxy | 48 | 97.92% | 85.42% | 12.50% | 2.08% |

MES closely reproduces independent public work reporting roughly 96%-98%
any-side breaks and about 69%-74% single-direction sessions. The 48-session NQ
single-break estimate is too noisy to compare seriously with a claimed 83.59%.
The complete-session SPY subset is provisional because IEX is not consolidated.

For 15-minute ranges, MES and SPY breached at least one side in every complete
session, but double breaks were more common than single breaks: 61.55% for MES
and 57.91% for SPY.

## Probability is not expectancy

The transparent aggressive-close proxy produced striking destination
frequencies:

- MES 15m opposite boundary eventually swept: 95.44% of 592 sessions.
- MES 60m opposite boundary eventually swept: 91.60% of 595 sessions.
- SPY 15m opposite boundary eventually swept: 94.44% of 234 sessions.
- SPY 60m opposite boundary eventually swept: 92.59% of 243 sessions.

Those figures ignore whether an equal-risk stop is reached first. Executable
1:1 aggressive-close sweep results were:

| Market/window | Trades | Target hit | Positive return | Net expectancy | PF |
|---|---:|---:|---:|---:|---:|
| MES 15m | 545 | 42.02% | 37.25% | -0.8580R | 0.1881 |
| MES 60m | 562 | 48.40% | 45.73% | -0.5217R | 0.3689 |
| SPY 15m | 189 | 36.51% | 31.22% | -1.3570R | 0.1178 |
| SPY 60m | 218 | 46.79% | 40.83% | -0.7676R | 0.2714 |
| NQ proxy 15m | 23 | 17.39% | 17.39% | -1.2096R | 0.0947 |
| NQ proxy 60m | 26 | 38.46% | 38.46% | -0.4383R | 0.4478 |

The social destination probability can be directionally true while the trade
is deeply unprofitable. It does not encode path, adverse excursion, stop
placement, or costs.

## Best fixed challenger

The least-bad rule was the 60-minute close-confirmed breakout with an
opposite-range stop and 1R target:

| Market | Trades | Target | Positive | Gross / cost / net | PF | 95% CI | Familywise CI |
|---|---:|---:|---:|---:|---:|---:|---:|
| MES | 1,073 | 28.15% | 52.28% | +0.0468 / 0.0393 / +0.0075R | 1.0219 | [-0.0392, +0.0513] | [-0.0528, +0.0712] |
| SPY | 398 | 27.89% | 51.01% | +0.0217 / 0.0383 / -0.0166R | 0.9540 | [-0.0958, +0.0662] | [-0.1204, +0.0923] |
| NQ proxy | 46 | 26.09% | 60.87% | +0.1708 / 0.0080 / +0.1628R | 1.8047 | [-0.0410, +0.2808] | [-0.0910, +0.3427] |

MES is flat after costs and its later segment is -0.0346R. SPY is negative
aggregate and its IEX sample is provisional. NQ looks better but has only 46
trades, only 10 later trades, and both intervals include zero. It is unresolved
insufficient evidence, not a deployable MNQ edge.

## Claim-matching limits

Edgeful's exact event definitions are proprietary. The lab uses transparent
definitions frozen before the accepted run and cannot exactly replicate or
falsify the posted 65%, 82.68%, or 83.59% figures.

As a direct check, MES high-first sessions with a 60-minute IB close in the
50%-75% zone swept the low 60.44% of the time, but there were only 91 such
sessions and the statistic still defines no entry or stop. The comparable
complete-SPY sample was only 30 sessions.

Independent public datasets support the broad frequency, not an implied trade:

- Steady Turtle reports 97.0% NQ and 97.8% ES any-side IB breaks over
  2020-mid-2026.
- TradingStats reports 96.2% NQ and 97.8% ES any-side breaks over 2015-2025,
  with roughly 69% ES / 74% NQ single-direction sessions.
- NQStats reports 96.1% NQ any-side breaks over ten years and shows that close
  location plus first extreme changes conditional direction.

## Adversarial review

An independent read-only reviewer attacked session boundaries, look-ahead,
fill ordering, costs, uncertainty, claim matching, and test coverage. The
accepted fixes were:

1. Complete-session enforcement and 16:00 exclusion.
2. Target-hit separation from positive EOD returns.
3. Gross, cost, and net R reporting.
4. Correct five-trade bootstrap labeling and familywise intervals.
5. Source hashes, timestamp, and cost provenance.
6. Direct 50%-75% and one-sided high-first descriptive fields.
7. Regression coverage for incomplete sessions and cost metrics.

The reviewer found no material look-ahead. The narrow conclusion survived:
high descriptive IB frequencies do not, by themselves, establish a profitable
executable edge. This does not claim every possible IB strategy is unprofitable.

## Decision

- Reject the three opposite-boundary sweep implementations under these rules.
- Do not add these rules to the Alpaca options bot.
- Do not enable the Topstep/MES simulator.
- Do not infer 0DTE performance from SPY underlying bars.
- Keep existing passing momentum, turn-of-month, and PEAD lanes unchanged.
- A future IB challenger needs materially different information or a precisely
  documented external rule and must be preregistered before reopening data.

## Confidence

- Broad 60-minute IB break frequency is real: 9.5/10.
- Screenshots alone define a profitable executable edge: 1/10.
- Fixed 60-minute breakout is ready for deployment: 0/10.
- This experiment should remain research-only: 9.5/10.
