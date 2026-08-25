# Trading Hypothesis Preregistration — MNQ SMT-Only (ablation)

Preregistration Schema: hypothesis-v2
Spec ID: mnq-smt-only-v1
Family ID: mnq-smt-cisd-family
Origin: research
Status: frozen
Spec Hash: sha256:b2680f71689b392dda80a1ffd5a1a5bac4453edee8e1e4e5801a01d6fca12bd0
Universe ID: cme-mnq-smt-family
Universe Version: cme-mnq-nq-mes-es-front-month-roll8-v1
Universe Hash: sha256:84d8ceaebd9f55d346059aba4809f8389fbe26099cd7878b0498c12dcd11ddbe
Membership As Of: 2026-08-24

Ablation of `mnq-smt-cisd-fvg-v1`. Tests whether SMT divergence alone (no
prior-day level requirement, no CISD, no FVG retrace) produces edge. Isolates
the SMT signal in the composite.

## Entry Rule

1. Completed H1 MNQ candle where MNQ prints a lower low than the prior H1 low
   AND ES/MES does NOT (bullish SMT), or MNQ prints a higher high than the
   prior H1 high AND ES/MES does NOT (bearish SMT).
2. Divergence magnitude gate: |MNQ_return - ES_return| on the divergence H1 bar
   ≥ 0.15% (return-normalized).
3. Entry on completion of the H1 bar that carries the divergence.
4. First divergence of the RTH session only.

## Exit Rule

- Stop: opposite side of the divergence H1 bar plus 1 tick.
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

America/New_York, completed H1 bars only.

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
