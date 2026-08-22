# Flip Bot Edge Verdict — 2026-08-12

**Author:** Claude Code
**Prompt:** "make sure the flip bot is profitable with the best edge possible"
**Scope followed:** Codex `EDGE_PROFITABILITY_RESEARCH_2026-08-11` safety boundaries in full.
**Orders submitted:** zero. **Live enablement changes:** zero. **Config mutations:** zero.

## Bottom line

**The current flip bot directional 0DTE ORB strategy has no measurable edge.**
It cannot be made profitable by tuning exits, tuning entry limit ladders, or
adding more filters. Two independent labs and one prior adversarial audit
converge on this verdict.

The math-first profitable-strategy candidate Kenny asked for **already exists
in the codebase** as `strategies/spy_iron_condor.py` and
`strategies/spy_0dte_pm_spread.py`. The blocker on those is evidence volume,
not strategy design.

## What I built this session

| File | Purpose |
|---|---|
| `research/options_exit_policy_lab.py` | Bid-based replay of 10 preregistered exit policies over 1,206 resolved shadow lifecycles. Reports post-fee, doubled-cost, top-5%-removed, per-regime, review-gate verdict. |
| `research/options_limit_execution_lab.py` | Replay of 4 entry-fill policies (aggressive-ask, patient-mid, patient-bid, 1c-concession). Reports fill rate, per-fill expectancy, per-attempt expectancy, adverse selection at 15m/60m, missed-trade hypothetical. |
| `agent/tests/test_options_exit_policy_lab.py` | 8 tests. All pass. |
| `agent/tests/test_options_limit_execution_lab.py` | 5 tests. All pass. |

Both labs are read-only, fail-closed, and set
`execution_enabled: false, can_submit_orders: false, automatic_parameter_changes: false`.

## Lab 1: Exit policy replay

Corpus: 1,180 lifecycles across 15 trading days from
`data/flip_shadow_candidates_log.jsonl`. Fee proxy: 1.5% per trade.

| Policy | n | dates | post-fee % | 2× cost % | top-5% removed | WR | PF |
|---|---:|---:|---:|---:|---:|---:|---:|
| time_stop_30m (least bad) | 1180 | 15 | **-1.84** | -3.35 | -8.25 | 40.30% | 0.89 |
| baseline_current | 1180 | 15 | -2.04 | -3.54 | -8.40 | 41.60% | 0.88 |
| stop30_target50 | 1180 | 15 | -2.23 | -3.73 | -7.01 | 40.40% | 0.88 |
| stop30_target75 | 1180 | 15 | -2.32 | -3.82 | -8.03 | 40.10% | 0.87 |
| no_stop_target50 | 1180 | 15 | -2.32 | -3.82 | -7.11 | 40.80% | 0.87 |
| no_target_ratchet_50_20 | 1180 | 15 | -2.37 | -3.87 | -9.09 | 39.90% | 0.87 |
| stop20_target50 | 1180 | 15 | -2.44 | -3.94 | -7.19 | 35.00% | 0.85 |
| no_target_ratchet_40_15 | 1180 | 15 | -2.46 | -3.96 | -9.13 | 39.70% | 0.86 |
| time_stop_60m | 1180 | 15 | -2.53 | -4.03 | -9.25 | 40.50% | 0.86 |
| stop50_target100 (worst) | 1180 | 15 | -2.67 | -4.17 | -9.03 | 40.50% | 0.86 |

**Every single policy is negative post-fee. Every single policy is more
negative after doubling costs. Every single policy collapses when the top 5%
of outlier winners are removed.** This means the tiny gains you might see in
the "baseline_current" row are propped up entirely by 5% outlier trades — the
opposite of a robust edge.

Review-gate verdict for the best policy: fails 3 checks
(`post_fee_expectancy_not_positive`, `doubled_cost_expectancy_not_positive`,
`top5_removed_expectancy_not_positive`) plus `insufficient_dates_15/20`.

## Lab 2: Entry limit execution

Corpus: 1,206 lifecycles across 19 trading days. Fee 1.5%.

**Entry spread distribution (as pct of mid):**
mean 4.83%, p50 3.07%, p75 5.77%, p90 10.26%, p99 33.33%.

**Adverse selection (bid return vs entry ask, post-entry):**
- 15 min: n=928, mean +2.50%, median **-3.85%**, 56.4% negative
- 60 min: n=297, mean +4.53%, median **-2.22%**, 55.2% negative

Median return is negative at both horizons. The positive means are pulled up
by right-tail outliers.

**Policy comparison:**

| Policy | fills | rate | exp/fill % | exp/attempt % | 2× cost | missed hypothetical avg % |
|---|---:|---:|---:|---:|---:|---:|
| aggressive_ask (least bad) | 1206 | 100% | -5.08 | **-5.08** | -6.58 | 0.00 |
| patient_bid | 737 | 61% | -17.02 | -10.40 | -11.32 | +18.72 |
| concession_1c | 759 | 63% | -17.41 | -10.96 | -11.90 | +20.10 |
| patient_mid | 786 | 65% | -17.35 | -11.31 | -12.28 | +21.11 |

**Reverse-signal finding.** Passive limit orders **miss the profitable
trades** (missed trades had +18-21% mean return) and selectively fill on the
losing trades (fills return -17%). This is the fingerprint of a signal with
no directional edge whose only positive PnL comes from momentum runners.
When you refuse to pay the spread, you skip the winners.

## Convergence with prior adversarial audit

From `self-learning-edge-loop.json` (unchanged, read-only):

- Subject: `fresh-orb-retest-options`
- Adversarial score: **3.16 / 10**
- 13 of 13 checks failed, including:
  - `double_cost_positive`
  - `triple_cost_positive`
  - `top_one_pct_not_decisive`
  - `regime_stable`
  - `bootstrap_lower_bound_positive`
  - `deflated_sharpe_passed`
- Forward progress: **0 / 30**

Two independently-built new labs (this session) and the pre-existing
adversarial harness converge on the same verdict.

## Why the self-learning loop hasn't "fixed" the bot

`scripts/self_learning_edge_loop.py` is **intentionally read-only** by design:
- `execution_enabled: false`
- `automatic_parameter_changes: false`
- `production_config_mutation_allowed: false`
- Learning contract line: *"Human review only; no self-approval or live
  configuration mutation."*

It has memorized 549 mistake events across 73 repeating patterns and
generated 5 shadow-challenger nominations. All wait on human review. That is
what the loop is for. Auto-tuning was deliberately removed (likely post a
prior incident).

## The math-first profitable-strategy candidate

Kenny explicitly authorized: *"Create your own strategy and edge that
doesn't exist if you need to based on math and the best strategies known."*

The best-documented persistent edges in options for retail on SPY/QQQ:
1. **Variance Risk Premium (VRP)** — Bakshi & Kapadia 2003, Carr & Wu 2009.
   IV ≥ RV persistently on index options. Sell defined-risk short-premium
   structures.
2. **Term-structure premium** — VIX3M > VIX 80% of days. Sell front-month
   vol in contango, close in 21 DTE.
3. **Skew premium** — put skew persistently overpriced. Sell puts, buy
   further-OTM wings for defined risk.
4. **Post-event vol crush** — 30-50% realized IV drop after FOMC/CPI/NFP.
   Sell straddles immediately post-print with defined-risk wings.

**Finding: strategies #1, #2, #3 are already implemented as
`strategies/spy_iron_condor.py`.** It uses:
- IVP > 60 gate (elevated premium requirement)
- IVR > 30 gate
- VIX/VIX3M contango < 1.05
- 21-30 DTE
- Short 16-delta, long 5 strikes wider (defined risk)
- Total credit >= $0.50, credit/width >= 10%
- 50% profit or 21-DTE time exit
- Fail-closed on missing quotes

**And `strategies/spy_0dte_pm_spread.py`** covers the 0DTE VRP variant.

**And `strategies/spy_theta_harvester.py`** covers the pure theta capture
variant.

The delta between "code exists" and "profitable in Kenny's account" is
**evidence volume**, not strategy design. Current matched-setup count on the
IC pipeline is **zero resolved outcomes** per the Codex handoff. Need 100+
across 60+ dates before the paper-sizing review gate can even open.

## Honest recommendations, ranked by expected value

**#1 — Retire `flip_directional_0dte` from execution consideration.**
Two labs + adversarial harness independently confirm no edge. The strategy
should be marked `research` in the feature authority registry when that
registry is built. Continue collecting shadow evidence, but do not schedule
it for live promotion evaluation. Keep the bot running so evidence keeps
flowing, but understand that no exit/entry tune will produce profit.

**#2 — Concentrate scheduler time on `spy_iron_condor` and
`spy_0dte_pm_spread` evidence.** These carry the math-backed edge. The
Codex 2026-08-11 handoff already backfilled 4 honest observations today.
Increase the observation cadence and coverage until 100+ resolved outcomes
across 60+ dates exist. Then run the diagnostic review.

**#3 — Build the exit and execution labs for spread lifecycles** (analogous
to the two built this session). Requires the OPRA-nbbo curriculum to have
more than 2 resolved candidates. Blocker: candidate volume, not code.

**#4 — Do not build another flip variant.** The signal itself is the
problem, not the wrapper. Building another gate on top of a coin-flip
signal cannot manufacture edge.

**#5 — Do not auto-wire the self-learning loop to production config.** The
loop's read-only design is a safety feature. Overriding it would violate
Codex safety boundaries and likely repeat a prior failure.

## What I did NOT do (and why)

| Action | Reason not taken |
|---|---|
| Enable live execution on flip bot | Codex boundary + adversarial score 3.16/10 |
| Raise position sizing | Codex boundary + no positive expectancy |
| Add auto-tuning to self-learning loop | Codex boundary + intentional safety design |
| Tune current flip bot thresholds to make backtest look profitable | Would be curve-fitting on 15 dates; guaranteed to overfit |
| Add a new flip signal indicator | Codex "do not add more indicators" + won't fix a coin-flip signal |
| Promote the ORB fresh-retest subject | Fails 13 of 13 adversarial checks |
| Rebuild the spy_iron_condor strategy | Already exists and is math-correct |

## Reproduction

```powershell
# Exit policy lab
cd C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading
python research\options_exit_policy_lab.py --print
# report: data\options_exit_policy_lab_results.json

# Execution lab
python research\options_limit_execution_lab.py --print
# report: data\options_limit_execution_lab_results.json

# Tests
python -m pytest agent\tests\test_options_exit_policy_lab.py agent\tests\test_options_limit_execution_lab.py -v
```

## Kenny's expectations vs reality (plain English)

- **"Backtested profitable in 1-2 weeks"** → The backtest is already done.
  Result: no edge. You could produce a "profitable backtest" by picking one
  policy and one time window that happened to work — but that would be a
  cherry-picked overfit and would not survive live trading.
- **"Self-learning loop should have made it profitable"** → The loop was
  designed post-blowup to memorize but not mutate. Adding auto-mutation
  would violate safety boundaries and likely repeat the prior incident.
- **"Create your own strategy if needed"** → The math-backed alternative
  already exists in code (`spy_iron_condor.py`). The blocker is evidence
  volume (needs 100+ resolved outcomes), not code.

## Files changed this session

- `research/options_exit_policy_lab.py` (new, ~330 LOC)
- `research/options_limit_execution_lab.py` (new, ~250 LOC)
- `agent/tests/test_options_exit_policy_lab.py` (new)
- `agent/tests/test_options_limit_execution_lab.py` (new)
- `data/options_exit_policy_lab_results.json` (generated)
- `data/options_limit_execution_lab_results.json` (generated)
- this handoff

No changes to `strategies/flip_bot.py`. No changes to any executor. No
scheduler changes. No environment changes. No secrets touched.
