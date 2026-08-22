# Codex Handoff: Options Timeframe and Confluence Evidence

Date: 2026-08-10 (America/Chicago)

## Objective

Measure whether options time horizon and confluence improve conservative
forward-shadow outcomes without turning popular heuristics into unearned live
gates. No order route was added or enabled.

## What Changed

- Added `scripts/options_confluence.py`.
  - Stable DTE buckets: 0, 1-4, 5-7, 8-20, 21-30, 31-45, and 46+ DTE.
  - Eastern-time entry buckets.
  - Independent labels for IVR, maturity-matched net VRP, VIX term structure,
    event coverage, trend alignment, and executable entry friction.
  - Exact confluence-cohort summaries with 30 resolved outcomes and 20 distinct
    dates required before statistical review.
  - Every cohort remains `promotion_eligible: false` and requires human review.
- Wired the analysis into `scripts/options_shadow_twin.py` as
  `timeframe_confluence`.
- Wired a read-only confluence snapshot into
  `strategies/spy_theta_harvester.py`.
  - IVR/IVP is read point-in-time from `data/iv_history_log.jsonl`.
  - Accumulating IVR history remains unavailable and cannot block or approve.
  - Maturity-matched IV versus RV remains the theta volatility gate.
- Added focused coverage to:
  - `agent/tests/test_options_shadow_twin.py`
  - `agent/tests/test_spy_theta_harvester.py`

## Research Corrections

Do not implement the pasted rules as universal facts.

- A 16-delta short option is not a 95% realized win-rate claim. Delta is not a
  calibrated physical probability of profit.
- `IVR > 30`, `IVP > 50`, and `IVP > 60 = 56.8% wins` need a named dataset,
  contract definition, costs, dates, and out-of-sample test before promotion.
- A 50% profit target and 21-DTE exit are management hypotheses, not laws.
- Five-to-seven DTE is not universally the worst horizon; strategy, skew,
  events, and execution costs determine the result.
- No primary evidence found supports moving all 0DTE entries to 12-2 PM ET.
  Intraday jump and dealer-gamma research supports measuring time and regime,
  not a blanket noon gate.

Primary references:

- Federal Reserve VRP overview:
  https://www.federalreserve.gov/pubs/FEDS/2010/201014/
- Federal Reserve macro-event option premium:
  https://www.federalreserve.gov/econres/ifdp/the-price-of-macroeconomic-uncertainty-evidence-from-daily-options.htm
- 0DTE trading, gamma risk, and volatility propagation:
  https://papers.ssrn.com/sol3/Delivery.cfm/4692190.pdf?abstractid=4692190&mirid=1
- Intraday jumps and 0DTE options:
  https://papers.ssrn.com/sol3/Delivery.cfm/5223127.pdf?abstractid=5223127&mirid=1
- Intraday option reversals:
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5081696
- Cboe PUT methodology:
  https://cdn.cboe.com/api/global/us_indices/governance/PUT_Methodology.pdf
- Cboe one-week putwrite methodology:
  https://cdn.cboe.com/api/global/us_indices/governance/WPTR_Methodology.pdf

## Current Evidence

### Flip 0DTE Time Buckets

Fresh report built from 890 completed primary shadow lifecycles. These are
cost-adjusted shadow observations across the existing universe, not broker
fills and not proof of causality.

| ET bucket | N | Win rate | Raw expectancy | Selector-adjusted expectancy |
|---|---:|---:|---:|---:|
| 09:30 | 141 | 46.1% | +2.58% | -0.92% |
| 10:00 | 99 | 40.4% | -1.89% | -5.39% |
| 10:30 | 104 | 40.4% | -3.38% | -6.88% |
| 11:00 | 87 | 42.5% | +0.08% | -3.42% |
| 11:30 | 96 | 37.5% | -6.42% | -9.92% |
| 12:00 | 90 | 44.4% | -4.91% | -8.41% |
| 12:30 | 89 | 38.2% | -6.28% | -9.78% |
| 13:00 | 94 | 33.0% | -10.16% | -13.66% |
| 13:30 | 70 | 32.9% | -4.98% | -8.48% |

Conclusion: do not move Flip to noon. No time bucket currently has positive
selector-adjusted expectancy. `time_gate_authority` remains `none`.

### Options Shadow Twin

- Candidates: 3
- Resolved: 3
- Earned confidence: 3.0/10
- Exact confluence cohorts: 2
- Cohorts ready for statistical review: 0
- Authority: `read_only_attribution_no_execution`

### IVR Readiness

SPY currently has 6 of the required 30 point-in-time readings. IVR and IVP are
therefore unavailable. Do not use fallback 50 as evidence and do not block the
theta shadow solely because IVR is still accumulating.

## Tuesday, August 11 Runbook

Expected Central-time tasks:

- 08:27 `Flip-Bot-Event-Monitor`
- 08:35 `Flip-Bot-Entry`
- 08:40 `Flip-Bot-Exploration`
- 08:45 `VibeTradingOptionsShadowTwin`
- 08:45 onward Flip monitor rotation
- 09:00 `SPY-Theta-Harvester-Monitor`

The theta entry is Monday-only and next runs August 17 at 08:45 CT. The Tuesday
theta monitor should report no open state. That is correct behavior.

Claude Code should:

1. Before 08:27 CT, verify the six tasks above are Ready and their actions point
   to this repo. Do not edit credentials or print secrets.
2. Keep all paper/shadow execution settings unchanged. Do not force a trade,
   move Flip to noon, enable live orders, or bypass a blocker.
3. After 09:05 CT, inspect task result codes and the latest Flip, options-twin,
   and theta decision artifacts. Classify data failures separately from valid
   no-trade decisions.
4. Confirm the options twin report contains `timeframe_confluence`, has
   `execution_enabled: false`, and has no statistically ready cohort.
5. At end of day, regenerate the Flip time-bucket report and compare only
   forward increments. Do not tune from the cumulative winner.
6. Preserve the 30-resolved/20-date cohort floor. Any 21-30 DTE iron-condor
   work stays shadow-only and requires fresh executable four-leg quotes,
   complete event coverage, fees, and an explicit policy cohort.

Useful commands:

```powershell
Get-ScheduledTask | Where-Object {$_.TaskName -match 'Flip|Theta|OptionsShadowTwin'} |
  Select-Object TaskName, State

python scripts/options_shadow_twin.py --report-only
python scripts/flip_shadow_time_bucket_report.py
python -m pytest agent/tests/test_options_shadow_twin.py agent/tests/test_spy_theta_harvester.py agent/tests/test_flip_shadow_time_bucket_report.py -q
```

## Verification

- Focused: 45 passed.
- Full repository: 4,544 passed, 4 skipped, 4 deprecation warnings.
- No orders were submitted.
- No execution flag, schedule, sizing rule, entry threshold, or exit policy was
  changed in this work.
