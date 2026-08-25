# Trading Hypothesis Preregistration — MNQ CISD-Only (ablation)

Preregistration Schema: hypothesis-v2
Spec ID: mnq-cisd-only-v1
Family ID: mnq-smt-cisd-family
Origin: research
Status: frozen
Spec Hash: sha256:b55a94d9663662eb59d18a6eb23af8808ac752bb015fb676005d716680719b4a
Universe ID: cme-mnq-smt-family
Universe Version: cme-mnq-nq-mes-es-front-month-roll8-v1
Universe Hash: sha256:84d8ceaebd9f55d346059aba4809f8389fbe26099cd7878b0498c12dcd11ddbe
Membership As Of: 2026-08-24

Ablation of `mnq-smt-cisd-fvg-v1`. Tests whether Change In State of Delivery
alone (no prior-day level, no SMT, no FVG) produces edge. Isolates the CISD
signal in the composite.

## Entry Rule

1. Compute 5m MNQ swing pivots (2-bar left, 2-bar right). Track most recent
   swing high and swing low.
2. Bullish CISD: first completed 5m bar that closes above the most recent 5m
   swing high AND prints a low below the prior 5m bar's low (state flip).
3. Bearish CISD: mirror.
4. Volume gate on CISD bar: ≥ 1.2× prior 20-bar 5m average.
5. First CISD of the RTH session only.

## Exit Rule

- Stop: opposite extreme of the CISD bar plus 1 tick.
- T1: 1R (50% off).
- T2: 2R (remainder).
- Trail after T1 to entry + 0.25R.
- Flat 30m before ETH close if unresolved.
- Adverse-first on intrabar order.

## Position Sizing

- 0.5% account risk. Max 10 concurrent MNQ.

## Universe

Same frozen membership as main family.

## Timestamp Basis

America/New_York, completed 5m bars only.

## Execution Policy

execution_enabled=false
can_submit_orders=false

## Cost Stress

$0.35/side commission plus 1 tick slippage. Positive net EV lower 95% CI at
base + doubled costs.

## Experiment Family & Multiple Testing

Registered under `mnq-smt-cisd-family`. Benjamini-Hochberg at α=0.05.

## Regime Coverage

≥100 outcomes, ≥30 dates, ≥8 per regime.

## Latency Budget

p90 alert latency ≤20% of expected window; ≥30 alerts.

## Blocker EV Review

Standard blocker EV review applies across blocked winners and losses using
net-after-cost expectancy, never raw winner counts.

## Data Repair & Backfill

Standard family rule.

## Decay & Revalidation

Three rolling windows, positive Brier skill, ≤30-day revalidation.

## Promotion Blockers

Evidence Tier: proxy_ohlcv_non_executable
Evidence Blockers:
  - databento_mbo_required
  - executable_futures_bbo_required
  - kenny_signoff_required

## Universe Version

Immutable identity per family policy.
