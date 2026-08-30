# KidQuant Pairs Trading — Dashboard Intake and Shadow Scanner Specification

Date: 2026-08-23

Status: research complete; scanner specification **draft / not frozen**

Authority: research and manual decision support only; `execution_enabled=false`; `can_submit_orders=false`

## 1. Executive decision

The KidQuant notebook is useful as an educational sketch, not as production evidence or production code. Reuse four ideas:

1. search for a stable relative-value relationship instead of treating correlation as mean reversion;
2. estimate an explicit hedge relationship;
3. standardize the residual spread and wait for an extreme;
4. separate pair formation from later trading.

Do **not** copy its pair-selection result, raw `p < 0.05` rule, ratio/z-score implementation, trade loop, P&L, data source, or thresholds into the dashboard. The notebook selects ADBE/MSFT with future information, does not control 55 simultaneous tests, changes its z-score formula between exploration and trading, abandons its estimated hedge ratio, trades the same close that creates the signal, pyramids without limit, and reports cash rather than a capital- and cost-aware return.

The right dashboard input is a new shadow-only `pairs_stat_arb_v1` cohort scanner. It should freeze a 252-session formation window, evaluate the next 126 sessions without refitting that cohort, test only a declared peer-bucket universe, control the declared hypothesis family, require I(1)-compatible legs, stable two-way Engle–Granger evidence, a plausible residual half-life, structural stability, two-leg liquidity and cost headroom, and completed-bar timing. It must abstain whenever any gate is unavailable.

This does not create a known win probability. Until forward outcomes qualify, the highest display state is `QUALIFIED_SHADOW_REVIEW`, not “high-probability trade.”

## 2. Source boundary and reproducible target

Only the following primary sources were used:

- KidQuant notebook at immutable commit `8e86c88272e5e0aec6970fb3b95dc7f39813702f`: [PairsTrading.ipynb](https://github.com/KidQuant/Pairs-Trading-With-Python/blob/8e86c88272e5e0aec6970fb3b95dc7f39813702f/PairsTrading.ipynb)
- Official statsmodels documentation: [`coint`](https://www.statsmodels.org/stable/generated/statsmodels.tsa.stattools.coint.html), [`adfuller`](https://www.statsmodels.org/stable/generated/statsmodels.tsa.stattools.adfuller.html), [`breaks_cusumolsresid`](https://www.statsmodels.org/stable/generated/statsmodels.stats.diagnostic.breaks_cusumolsresid.html), and [`breaks_hansen`](https://www.statsmodels.org/stable/generated/statsmodels.stats.diagnostic.breaks_hansen.html)
- Gatev, Goetzmann, and Rouwenhorst, *Pairs Trading: Performance of a Relative Value Arbitrage Rule*: [NBER Working Paper 7032](https://www.nber.org/papers/w7032) and [paper PDF](https://www.nber.org/system/files/working_papers/w7032/w7032.pdf)
- Benjamini and Hochberg, *Controlling the False Discovery Rate*: [original 1995 paper](https://doi.org/10.1111/j.2517-6161.1995.tb02031.x)
- Gregory and Hansen, *Residual-based tests for cointegration in models with regime shifts*: [author page and paper](https://users.ssc.wisc.edu/~behansen/papers/joe_96.html)

No social-media P&L claim, tutorial, vendor backtest, or secondary strategy article is treated as evidence.

## 3. What is reusable

### 3.1 Cointegration is a hypothesis, not a chart resemblance

KidQuant correctly distinguishes correlation from cointegration and uses statsmodels' augmented Engle–Granger implementation. Official statsmodels documentation states that `coint` tests the null of **no cointegration**, assumes the input variables are I(1), includes a constant or trend in the first-stage relation, and returns MacKinnon approximate p-values and critical values. It also warns that near-collinearity can be numerically unstable and that NaNs/gaps are not handled automatically. [statsmodels `coint`](https://www.statsmodels.org/stable/generated/statsmodels.tsa.stattools.coint.html)

Production implication: the scanner must validate integration order, alignment, gaps, finite values, regression orientation, deterministic terms, lag policy, observations, and library version before a p-value can qualify a pair.

### 3.2 Formation and trading must be causally separate

Gatev et al. form pairs over 12 months and trade them in a later six-month period. Their method uses minimum distance between normalized historical price paths, not the KidQuant cointegration screen; their result therefore supports the **formation/trading discipline**, not KidQuant's exact model. The paper also explicitly recognizes transaction costs and possible market-microstructure effects. [Gatev et al., NBER](https://www.nber.org/papers/w7032)

Production implication: pair identity, hedge parameters, spread mean/scale, half-life, and selection rank are frozen before the first trading-period observation. No later bar may revise the historical decision record.

### 3.3 Relative-value plans need two legs and one lifecycle

The notebook estimates an OLS coefficient and shows how a residual spread can be standardized. A dashboard can reuse this geometry only if the same regression orientation and coefficient create both the statistical test and the tradable spread.

Production implication: one pair lifecycle owns both legs, hedge quantities, simultaneous-entry assumption, combined invalidation, combined cost, and combined outcome. Two independent single-stock cards are not a pairs trade.

### 3.4 Multiple testing belongs in the visible evidence

Benjamini and Hochberg define false discovery rate as the expected proportion of false rejections among rejections and give a sequential procedure for independent test statistics. [Benjamini–Hochberg 1995](https://doi.org/10.1111/j.2517-6161.1995.tb02031.x)

Production implication: the dashboard must show `tests_in_family`, raw p-value, BH cutoff/rank, adjusted q-value, and the family definition. Pairs share symbols and are statistically dependent, so the original paper's independence guarantee is not established for a dense all-pairs scan. `pairs_stat_arb_v1` therefore uses BH as a declared conservative selection gate plus additional stability gates, but must display `fdr_guarantee=not_established_for_shared_symbol_dependence`. A future dependence-robust method is a new hypothesis/spec version, not a silent substitution.

## 4. Exact audit of the notebook

| Notebook behavior | Exact problem | Production consequence / required replacement |
|---|---|---|
| `warnings.filterwarnings('ignore')` globally suppresses warnings. | It can hide missing-data, deprecation, numerical, and near-collinearity warnings that are material to `coint`. | Never suppress globally. Convert qualifying data/numerical warnings into structured blockers. |
| Eleven symbols produce all `11×10/2 = 55` pair tests; `find_cointegrated_pairs` accepts every raw `p < 0.05`. | No family definition or multiplicity adjustment. | Freeze the entire family and apply BH to all pair hypotheses from the cohort, including failures. |
| Output contains six raw discoveries, although prose later says “the two pairs”; ADBE/MSFT is reported at `p=0.0445269627`. | ADBE/MSFT cannot pass BH at `q=.05`: with 55 tests and at most rank 6, its largest possible BH cutoff is `6×.05/55=.00545`. The notebook's claim that it is “indeed cointegrated” is not justified after its own search. | Never promote a hand-picked raw p-value. Persist raw p, rank, cutoff, adjusted q, and all 55 outcomes. |
| ADF is demonstrated only on synthetic series; stock price levels/differences are not checked. | `coint` maintains that both inputs are I(1). Failure to reject an ADF null is not proof of a unit root. Official docs also say near-boundary ADF results should be judged against critical values. [statsmodels `adfuller`](https://www.statsmodels.org/stable/generated/statsmodels.tsa.stattools.adfuller.html) | Require explicit level and first-difference compatibility checks and label the result `I1_compatible`, never `proved_I1`. |
| Close data go directly into `coint`. | No finite-value, common-calendar, gap, stale-bar, minimum-observation, corporate-action, or total-return validation. | Use adjusted, aligned, completed daily observations; fail closed on gaps or insufficient coverage. |
| Pair search uses the complete 2013–2019 data before the later 70/30 split. | Future/test data select the pair and its p-value. | Pair formation uses only the closed formation window; all subsequent bars are out of sample for that cohort. |
| The first reported call trades `df.iloc[881:]`, while the later training boundary is observation 1057. | The displayed “test” overlaps observations 881–1056 with the later-declared training sample. | Declare all boundaries before computing selection, parameters, or outcomes. |
| Exploratory feature is `(MA5−MA60)/std60`; `trade(..., 60, 5)` computes `(MA60−MA5)/std5`. | Signal sign and scale both change. Comments describing long/short direction also conflict with code. | One versioned formula, golden-vector tests, and explicit rich/cheap leg mapping. |
| `coint(S1,S2)` is followed by `OLS(S2 ~ S1)`, then the backtest trades `S1/S2`. | Test orientation, displayed residual, and traded object are inconsistent. The estimated hedge coefficient is discarded. | Predeclare orientation; construct and trade exactly `log(Y)−alpha−beta·log(X)` from the frozen formation regression. |
| Each bar outside the threshold adds another unit. | Unlimited pyramiding and path-dependent leverage; no gross, net, or per-pair cap. | One entry per lifecycle; no pyramiding in v1. |
| Entry cash is computed with `S1−S2×(S1/S2)`. | It is algebraically zero before frictions and is not a capital requirement or executable two-leg fill. | Track gross notional, net exposure, buying power, both quotes/fills, and implementation shortfall. |
| Signal includes close `i` and is filled at close `i`. | Same-bar look-ahead/execution assumption: the completed close is not known early enough to guarantee that fill. | A completed-bar signal becomes actionable only on the next quote/bar. |
| Final `money` omits open inventory. | No forced liquidation or mark-to-market at sample end. | Every outcome closes at convergence, stop, time limit, cohort expiry, or final observable quotes. |
| P&L excludes dividends, spreads, slippage, commissions/fees, borrow cost, short availability, partial fills, and margin/capital. | The printed number is not an executable or comparable return. | Resolve gross and net P&L after a two-leg cost model; unfilled/one-legged cases remain in the denominator. |
| Window lengths 0–254 are optimized and the test-optimal window is also reported. | Large hidden experiment family and overfit selection; the notebook itself notes the problem. | Freeze all candidate parameters and count every tried variant before replay. No tuning from the forward ledger. |
| No dependency versions or data snapshot are pinned. | Results are not reproducible as APIs/defaults change; statsmodels documents an historical change in `coint` autolag behavior. | Pin package versions, input hashes, stats parameters, and cohort/spec hashes. |

## 5. Preregistered shadow scanner specification: `pairs_stat_arb_v1`

All thresholds below are engineering choices to freeze and test, not proven edge. Changing one creates a new experiment variant and family-ledger entry.

### 5.1 Authority and purpose

```text
provider = pairs_stat_arb_shadow_v1
mode = read_only_manual_decision_support
execution_enabled = false
can_submit_orders = false
orders_submitted = 0
```

Purpose: produce deterministic, point-in-time, two-leg relative-value setups for shadow review and outcome collection. It never sends an order, sizes a user's account, or displays a qualified win probability before forward calibration.

### 5.2 Universe and hypothesis family

1. Create a versioned `pairs_universe_v1` manifest before the first cohort. Each row contains `symbol`, `asset_type`, `peer_bucket`, `eligible_from`, `eligible_to`, and provenance.
2. Eligible assets: U.S.-listed common stocks and unlevered U.S. ETFs only. Exclude leveraged/inverse ETFs, preferreds, warrants, OTC securities, and symbols without point-in-time corporate-action-adjusted history.
3. Test only pairs inside the same preregistered peer bucket. No cross-bucket pair can be added after p-values are seen.
4. At formation end, each leg must have:
   - price at least `$10`;
   - at least 252 common completed daily observations;
   - at least 99% common-calendar coverage and no gap longer than two sessions;
   - 60-session median daily dollar volume at least `$100 million`;
   - finite positive adjusted prices throughout formation.
5. The FDR family is **every eligible within-bucket unordered pair on one cohort date under this exact spec**, not only successfully returned p-values. Failed tests remain `data_blocked` in the denominator.
6. Persist `eligible_assets`, `possible_pairs`, `tested_pairs`, `data_blocked_pairs`, and `m_tests`. Reconcile `possible_pairs = tested_pairs + data_blocked_pairs`.

Point-in-time limitation: a current static universe is valid only for forward shadow operation. A historical replay may not claim survivorship-free evidence without historical membership/effective dates.

### 5.3 Timeframes and clocks

| Role | Timeframe | Rule |
|---|---:|---|
| Formation / statistical model | 1 completed trading day | 252 common sessions ending at cohort cut; no bar from the trading period |
| Trading horizon | 1 day | Next 126 sessions, parameters frozen for that cohort |
| Health check | 1 day | Prior completed daily bar; deterministic residual/stop checks only |
| Entry trigger | 15 completed minutes | Used only after the prior daily close arms the pair |
| Execution context | quote + 5m liquidity | Freshness/spread/participation only; never another statistical vote |

- Cohorts form after each month-end close when all adjusted daily data are final.
- A cohort's first actionable observation is the next trading session.
- The signal timestamp is the close of the completed 15m bar; the earliest hypothetical/manual entry observation is the first fresh quote after that close.
- No 1m signal, incomplete bar, same-bar fill, or multi-timeframe “confluence” points are allowed in v1.
- Monthly cohorts may overlap, as in the spirit of Gatev's separated formation/trading periods, but the dashboard shows one newest qualified lifecycle per unordered pair. Older cohorts continue outcome tracking without creating duplicate cards.

### 5.4 Statistical formation gates

Use natural-log adjusted prices and pin the statsmodels version. For each alphabetically ordered unordered pair `(X,Y)`:

1. **I(1)-compatibility per leg**
   - `adfuller(log_price, regression="ct", autolag="BIC")`: level p-value must be `> .10` and the 10% critical value must not be crossed.
   - `adfuller(diff(log_price), regression="c", autolag="BIC")`: p-value must be `< .05` and the 5% critical value must be crossed.
   - Store statistic, p-value, critical values, used lag, nobs, and deterministic terms.
   - Otherwise block as `not_I1_compatible`; do not reinterpret failure to reject as proof.
2. **Two-way Engle–Granger robustness**
   - Run `coint(log(Y), log(X), trend="c", autolag="BIC")` and the reverse orientation on formation data only.
   - Define pair raw p-value as `max(p_yx, p_xy)`. This conservative rule requires both orientations to pass rather than selecting the better direction after seeing results.
   - Separately fit the tradable orientation fixed by alphabetical order: `log(Y)=alpha+beta·log(X)+epsilon`.
3. **BH gate**
   - Sort all pair raw p-values in the cohort family.
   - At `q=.05`, retain through the largest rank `k` satisfying `p_(k) <= k*q/m`.
   - Require pair `bh_selected=true`, pair raw p `<=.01`, and both directional p-values `<=.05`.
   - Store `m`, rank, BH cutoff, adjusted q-value, selected count, and the dependence disclosure.
4. **Hedge geometry**
   - Require finite `alpha`, positive `beta`, and `0.50 <= beta <= 2.00`.
   - Tradable residual is exactly `epsilon_t = log(Y_t)-alpha-beta*log(X_t)`.
   - Formation spread center and standard deviation are frozen. Require positive finite standard deviation and no single observation greater than eight formation standard deviations without a documented corporate-action explanation.

Why both orientations: Engle–Granger is asymmetric in a finite sample. Choosing the lower p-value after inspection would add another uncounted selection step.

### 5.5 Stability and half-life gates

1. Refit the same orientation on the first and second 126-session halves.
2. Both half-window `coint` p-values in both orientations must be `<=.10`.
3. Both half-window betas must be positive; each must differ from full-window beta by no more than 25% of `abs(beta_full)`.
4. Difference between the two half-window residual means must be no more than `0.75 × full_window_spread_std`.
5. On the full formation OLS residuals:
   - `breaks_cusumolsresid(resid, ddof=2)` must have `p >= .05`;
   - `breaks_hansen(ols_result)` must not exceed its 95% critical value for the model's parameter count.
   - Store test statistic, critical value/p-value, and package version. Official statsmodels describes these as OLS parameter-stability diagnostics and cautions that CUSUM power depends on regressors; they are gates, not proof of permanence. [CUSUM](https://www.statsmodels.org/stable/generated/statsmodels.stats.diagnostic.breaks_cusumolsresid.html), [Hansen stability test](https://www.statsmodels.org/stable/generated/statsmodels.stats.diagnostic.breaks_hansen.html)
6. Fit `epsilon_t = c + phi*epsilon_(t-1) + u_t` on formation residuals. Require `0 < phi < 1`; define exact discrete half-life as `log(0.5)/log(phi)` and require `3 <= half_life_sessions <= 60`.
7. A Gregory–Hansen result may identify cointegration under an unknown regime shift, but v1 must not use it to rescue an unstable pair. The authors note that their alternative includes the standard no-shift model, so it is not by itself proof that a break occurred. [Gregory–Hansen paper](https://users.ssc.wisc.edu/~behansen/papers/joe_96.html)

Any failure produces `stability_status=blocked`, never a lower-confidence trade card.

### 5.6 Entry arming and trigger

At prior completed daily close `D-1`, compute `z_daily` using the frozen cohort `alpha`, `beta`, spread center, and spread scale.

- `observe`: `abs(z_daily) < 1.75`
- `armed`: `1.75 <= abs(z_daily) < 3.25`
- `invalid_extreme`: `abs(z_daily) >= 3.25`

During session `D`:

1. Recompute the same frozen spread from each completed 15m pair of closes.
2. Record `pending_extreme` after `abs(z_15m) >= 2.00`.
3. Emit `QUALIFIED_SHADOW_REVIEW` only on a later completed 15m bar when:
   - `abs(z_15m)` has contracted by at least `0.10` from the pending extreme;
   - it remains at least `1.75` and below `3.25`;
   - both leg quotes and 5m liquidity pass Section 5.8;
   - no lifecycle for that unordered pair is already open;
   - every formation/stability gate remains qualified.
4. If `z > 0`, Y is rich: shadow plan is short Y and long beta-adjusted X. If `z < 0`, Y is cheap: long Y and short beta-adjusted X.
5. Do not pyramid, reverse, or chase. A new outward extreme while open updates MFE/MAE only.

This confirmation is a preregistered timing rule, not a claim that reversal candles improve returns. Its value must be tested against a sidecar that enters on the first completed 15m `|z| >= 2` observation; both variants count in the experiment family.

### 5.7 Exit and invalidation

For one immutable two-leg plan:

- **Target exit:** first completed 15m bar with `abs(z) <= 0.50`; hypothetical fill uses the next fresh two-leg quotes.
- **Protective invalidation:** first completed 15m bar with `abs(z) >= 3.25` after entry.
- **Time stop:** after `min(ceil(3*half_life_sessions), 60)` trading sessions.
- **Cohort stop:** mandatory liquidation no later than the cohort's 126th trading session.
- **Data stop:** quarantine immediately if either leg is stale, halted, missing, delisted, or has an unresolved corporate action. Do not fabricate an exit; resolve at the next documented executable observation and label the gap.
- **Borrow stop:** no entry if the required short leg is not shortable/easy-to-borrow under the existing broker read. A later borrow loss is an explicit manual-risk alert.
- **One-leg event:** a partial/manual one-leg execution is not a valid pair fill. It remains an execution incident in the denominator.

### 5.8 Liquidity and cost gates

At the actionable quote after the completed trigger bar:

1. Both quotes must be positive, uncrossed, and no older than 15 seconds under a synchronized local clock.
2. Each leg's quoted spread must be no more than 15 bps.
3. Each leg must retain 60-session median daily dollar volume of at least `$100 million`.
4. A `$10,000` reference-gross shadow trade must be no more than 0.10% of each leg's 20-session average daily dollar volume and no more than 1% of its median completed 15m dollar volume.
5. Allocate reference gross by the frozen log hedge: `notional_Y = gross/(1+beta)` and `notional_X = beta*gross/(1+beta)`. Show gross notional, net dollar exposure, and beta-adjusted exposure; do not call it perfectly market-neutral.
6. Estimated round-trip cost includes four half-spreads, four declared slippage charges, fees, and borrow cost for the expected holding period. Missing spread, slippage policy, short availability, or borrow assumption blocks `QUALIFIED_SHADOW_REVIEW`.
7. Approximate gross convergence value at target is `notional_Y * (abs(z_entry)-0.50) * spread_std`. Require it to be at least `3.0 × estimated_round_trip_cost` and positive after a 2× cost stress.
8. Persist both the model estimate and its assumptions. Outcome truth uses actual/manual two-leg fills where available, including partial/unfilled attempts.

Market-data coverage must be labeled exactly as supplied by the existing provider. A single-venue quote cannot be presented as consolidated best bid/offer.

### 5.9 Outcome and promotion contract

Each trigger creates one stable `pair_lifecycle_id` and immutable `plan_hash`. Resolve:

- both intended entry quotes and any actual/manual fills;
- entry synchronization delay and one-leg exposure;
- target/stop/time/cohort exit reason;
- gross and net P&L, gross and net return on reference gross;
- MFE/MAE in spread z and dollars;
- holding sessions/minutes;
- estimated versus realized costs;
- matched, ambiguous, unmatched, partial, or unfilled status;
- cohort, peer bucket, feed, spec, statsmodels, universe, and cost-model hashes.

Unfilled and ambiguous records stay in the denominator. No threshold is tuned from this forward ledger. Promotion requires a separate frozen rule and chronological evidence; until then probability is `unavailable_unqualified`.

## 6. Dashboard payload

Recommended read-only report: `~/.vibe-trading/reports/pairs-stat-arb-shadow.json`

```text
{
  schema_version,
  provider: "pairs_stat_arb_shadow_v1",
  generated_at,
  status,
  mode: "read_only_manual_decision_support",
  execution_enabled: false,
  can_submit_orders: false,
  source_inventory,
  cohort_reconciliation: {
    universe_count, eligible_asset_count, possible_pair_count,
    tested_pair_count, data_blocked_pair_count, bh_selected_count,
    stable_pair_count, armed_pair_count, emitted_pair_count,
    denominator_reconciled
  },
  pairs: [...],
  errors,
  warnings
}
```

Every pair row must expose:

| Group | Required fields |
|---|---|
| Identity | `pair_lifecycle_id`, `plan_hash`, `symbol_x`, `symbol_y`, `peer_bucket`, `cohort_id`, formation start/end, trading expiry, universe/spec hashes |
| Point-in-time provenance | data provider/feed/coverage, timestamps and age for both legs, completed daily/15m cuts, package/data hashes, corporate-action adjustment |
| Integration | level/difference ADF statistic, p, critical values, lags, nobs for both legs; `I1_compatible` status |
| Cointegration/FDR | both directional test stats/p-values, pair max p, BH q/rank/cutoff/family size, selected count, dependence disclosure |
| Hedge/stability | alpha, beta, both half-window betas/p-values, beta drift, residual mean shift, CUSUM/Hansen results, phi, half-life, stability blockers |
| Live spread | frozen center/std, prior daily z, current completed-15m z, pending extreme, contraction, state, freshness |
| Plan | rich/cheap leg, leg sides, reference quantities/notionals, entry rule/time, target z, stop z, time stop, cohort stop, no-chase/no-pyramid flags |
| Feasibility | bid/ask/spread/age for both legs, dollar volume, participation, shortable/borrow assumption, estimated gross capture, base/stressed costs, cost multiple |
| Evidence | outcome count/dates, gross/net expectancy, calibration status, probability or explicit unavailable reason |
| Safety | `execution_enabled=false`, `can_submit_orders=false`, `orders_submitted=0` |

### Display hierarchy

1. `DATA_BLOCKED` — missing, stale, gapped, invalid, or unreconciled inputs.
2. `STATISTICALLY_REJECTED` — I(1), FDR, hedge, stability, or half-life gate failed.
3. `OBSERVE` — qualified formation relationship, no current divergence.
4. `ARMED` — daily divergence is near entry, not an entry.
5. `PENDING_REVERSAL` — 15m extreme occurred, confirmation incomplete.
6. `QUALIFIED_SHADOW_REVIEW` — all gates passed; manual review only.
7. `OPEN_SHADOW` / `EXIT_DUE` / `RESOLVED` — lifecycle states.

The card must show both legs and the joint plan. A green statistical label without borrow, quotes, costs, and both-leg freshness is prohibited.

## 7. Acceptance tests before dashboard wiring

1. **Causality:** changing any trading-period bar cannot change that cohort's pair selection, alpha, beta, mean, standard deviation, half-life, or BH result.
2. **No same-bar fill:** trigger from bar `t` can use only a quote strictly after bar `t` closes.
3. **Family completeness:** a known vector of p-values produces the expected BH rank/cutoff; failed pairs remain in `m` and reconciliation.
4. **Notebook counterexample:** ADBE/MSFT `p=.0445269627`, `m=55`, rank at most 6 cannot be selected at `q=.05`.
5. **I(1) gate:** stationary levels, nonstationary differences, NaNs, gaps, infinities, and insufficient observations all fail deterministically.
6. **Orientation:** the same frozen alpha/beta/residual powers coint reporting, live z, leg directions, outcomes, and postmortem.
7. **Stability:** synthetic intercept/slope breaks fail at least one preregistered stability gate; stable synthetic cointegration passes under seeded data.
8. **Half-life:** `phi <= 0`, `phi >= 1`, and half-life outside `[3,60]` block.
9. **Execution feasibility:** stale/crossed/wide/missing leg quotes, missing shortability, missing cost assumption, or failed 2× cost stress block readiness.
10. **Lifecycle:** repeated threshold bars do not pyramid or duplicate the pair; older overlapping cohorts remain outcome-only.
11. **Costs/outcomes:** terminal open positions are liquidated or explicitly unresolved; unfilled/partial/ambiguous manual records remain counted.
12. **Safety:** source scan and endpoint tests prove no POST/PATCH/PUT/DELETE path, credentials, account IDs, order IDs, or order authority.

## 8. Recommended implementation order

1. Freeze `pairs_universe_v1` and this spec, including the peer buckets and all thresholds.
2. Build pure data-validation, I(1), coint/FDR, stability, half-life, and cost functions with golden tests.
3. Build a monthly cohort generator and immutable cohort ledger; no dashboard yet.
4. Run causal walk-forward replay with all attempted pairs and variants counted.
5. Add completed-15m shadow lifecycle and outcome resolution.
6. Only then surface the payload in a dashboard `Pairs / Relative Value` panel.

Do not fork or import the notebook as a dependency. Reimplement the small validated concepts against the repository's existing point-in-time data, provenance, outcome, calibration, and daily-review contracts.

## 9. Final disposition

| Item | Decision |
|---|---|
| KidQuant notebook as executable dependency | Reject |
| KidQuant pair-selection/P&L result as edge evidence | Reject |
| Cointegration + residual spread concept | Reuse with the specified gates |
| Gatev formation/trading separation | Reuse |
| Raw `p < .05` across all pairs | Reject; use visible cohort-family FDR gate |
| Ratio MA z-score and trade loop | Reject |
| Dashboard integration now | Wait until cohort generator and causal tests are green |
| Execution authority | Permanently false for this scope |

The notebook is a useful teaching artifact. The production contribution is the disciplined, falsifiable shadow specification above—not its plotted signals or reported P&L.
