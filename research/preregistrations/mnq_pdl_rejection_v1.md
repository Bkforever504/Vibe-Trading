# Trading Hypothesis Preregistration — MNQ PDL/PDH Rejection (ablation)

Preregistration Schema: hypothesis-v2
Spec ID: mnq-pdl-rejection-v1
Family ID: mnq-smt-cisd-family
Origin: research
Status: frozen
Spec Hash: sha256:54cb3221c4fabdc9d04cf85ca9dcdf3f041883fab230feb113936969ca3732ba
Universe ID: cme-mnq-smt-family
Universe Version: cme-mnq-nq-mes-es-front-month-roll8-v1
Universe Hash: sha256:84d8ceaebd9f55d346059aba4809f8389fbe26099cd7878b0498c12dcd11ddbe
Membership As Of: 2026-08-24

Ablation of `mnq-smt-cisd-fvg-v1`. Tests whether prior-day level rejection
alone produces edge without the SMT or CISD or FVG layers. If this ablation
performs comparably to the full stack, the added layers are noise.

## Entry Rule

1. Completed 5m MNQ bar that wicks through PDH (short setup) or PDL (long
   setup) and closes back on the origin side by ≥ 40% of the bar's range.
2. Rejection candle volume ≥ 1.2× prior 20-bar 5m average.
3. First rejection of the session only; ignore subsequent PDH/PDL touches.

## Exit Rule

- Stop: 1 tick beyond the rejection candle extreme.
- T1: 1R (50% off).
- T2: 2R (remainder).
- Trail after T1 to entry + 0.25R.
- Flat 30m before ETH close if unresolved.
- Adverse-first on intrabar order.

## Position Sizing

- 0.5% account risk. Max 10 concurrent MNQ.

## Universe

Same frozen membership as main family:
`data/universes/mnq_smt_family_2026-08-24.json`.

## Timestamp Basis

America/New_York, completed 5m bars only. PDH/PDL from prior RTH
09:30-16:00 ET, computed at RTH close.

## Execution Policy

execution_enabled=false
can_submit_orders=false

## Cost Stress

$0.35/side commission plus 1 tick slippage. Positive net EV lower 95% CI at
base + doubled costs.

## Experiment Family & Multiple Testing

Registered under `mnq-smt-cisd-family`. Benjamini-Hochberg at α=0.05 across
exact ledger family size.

## Regime Coverage

≥100 outcomes, ≥30 dates, ≥8 per regime.

## Latency Budget

p90 alert latency ≤20% of expected window; ≥30 alerts.

## Blocker EV Review

New detector. Standard blocker EV rule applies.

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
