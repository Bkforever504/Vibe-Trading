# Trading Hypothesis Preregistration — MNQ SMT + CISD + FVG (main)

Preregistration Schema: hypothesis-v2
Spec ID: mnq-smt-cisd-fvg-v1
Family ID: mnq-smt-cisd-family
Origin: social
Status: frozen
Spec Hash: sha256:686aed721b83bc2e0c0051adc2af863f2eeee459874c8f13d275489c56b7bb2d
Universe ID: cme-mnq-smt-family
Universe Version: cme-mnq-nq-mes-es-front-month-roll8-v1
Universe Hash: sha256:84d8ceaebd9f55d346059aba4809f8389fbe26099cd7878b0498c12dcd11ddbe
Membership As Of: 2026-08-24

Frozen challenger sourced from social screenshot (MNQ 5-lot, $175 risk / $532.50
reward, ~3.04R). This spec preserves the sequence but adds mechanical
definitions the source did not provide. Promotion-ineligible on yfinance proxy;
requires Databento MBO + executable NBBO before any promotion review.

## Entry Rule

Four-stage sequence; all inputs use completed bars only.

1. **Prior-day level tag** — completed H1 candle on MNQ (or NQ) whose high
   crosses prior-day high (PDH) OR whose low crosses prior-day low (PDL). PDH/PDL
   from the prior RTH session 09:30-16:00 ET. Missing prior-day = skip.

2. **SMT divergence at that tag** — on the same completed H1 candle where MNQ
   tags PDL, ES/MES must NOT tag its own PDL (bullish SMT), and vice versa for
   PDH (bearish SMT). Divergence magnitude gate: |MNQ_return - ES_return| on the
   tag H1 bar ≥ 0.15% (return-normalized, not raw points).

3. **CISD confirmation on 5m** — inside the two H1 candles following the SMT
   tag, the first completed 5m MNQ bar that closes back through the tag level
   AND takes out the most recent 5m swing high (bullish CISD) or swing low
   (bearish CISD). Swing = pivot with two-bar left, two-bar right.

4. **FVG or order-block retrace entry** — after CISD, wait for MNQ to retrace
   into either:
   - **FVG:** three-bar imbalance where bar[n-2].low > bar[n].high (bearish FVG,
     used for shorts) or bar[n-2].high < bar[n].low (bullish FVG, for longs)
     formed on 5m during the CISD leg.
   - **Order block:** the last opposing-color 5m candle before the CISD leg,
     using its high/low as the zone.
   Enter on close of the first completed 5m rejection candle inside the zone
   (rejection = wick ≥ 60% of range, close in the CISD direction).

## Exit Rule

- Stop: opposite side of the FVG or order block (whichever tighter), plus 1 tick.
- T1 (50% off): 1R (R = entry to stop distance).
- T2 (remaining): 2R hard-frozen. Do not chase the 3R implied by social math —
  statistical humility until 100 outcomes prove it.
- Trail after T1: move stop to entry + 0.25R (long) / entry - 0.25R (short).
- Time exit: flat 30m before ETH close if not resolved.
- Adverse-first on unresolved intrabar order.

## Position Sizing

- 0.5% account risk per trade (MNQ = $2/point).
- `contracts = floor((equity * 0.005) / (stop_distance_pts * $2))`.
- Max 10 concurrent MNQ (spec source used 5).

## Universe

Frozen membership: `data/universes/mnq_smt_family_2026-08-24.json`. MNQ is the
sole tradable; NQ, MES, ES are context-only for SMT divergence. Membership
immutable.

## Timestamp Basis

America/New_York, completed bars only. H1 candle close at :00. 5m candle close
on 5-min grid. All SMT, CISD, FVG inputs must exist at decision timestamp.

## Execution Policy

execution_enabled=false
can_submit_orders=false
Shadow-log the sequence stages, level, SMT magnitude, CISD anchor, FVG/OB
geometry, entry, stop, targets, grade. No broker or order authority.

## Cost Stress

$0.35 commission per side per MNQ contract plus 1 tick ($0.50) slippage on
entry and exit. Require positive net expectancy lower 95% CI at base costs AND
under doubled commissions and slippage.

## Experiment Family & Multiple Testing

Frozen family: 4 candidates registered under `mnq-smt-cisd-family` (main + 3
ablations). Promotion uses Benjamini-Hochberg at α=0.05 with exact immutable
ledger family size. Missing raw p-values produce HOLD.

## Regime Coverage

≥100 resolved outcomes, ≥30 independent dates, ≥8 dates in each of trend,
chop, high-vol, low-vol. Point-in-time regime inputs.

## Latency Budget

Expected move window from CISD 5m close through the T2 hit or time-exit flat.
p90 alert latency ≤20% of that window; ≥30 alerts required.

## Blocker EV Review

New detector. Any later blocker change requires positive net-after-cost EV
lower 95% CI including blocked losses and winners.

## Data Repair & Backfill

Any repair to MNQ, NQ, MES, ES bars must identify affected interval, complete
point-in-time backfill, re-grade every affected outcome, leave zero
contaminated outcomes.

## Decay & Revalidation

Three rolling validation windows, positive latest Brier skill, revalidation
within 30 days. Stale/failing approved candidate returns to paper_review.

## Promotion Blockers

Evidence Tier: proxy_ohlcv_non_executable
Evidence Blockers:
  - databento_mbo_required
  - executable_futures_bbo_required
  - kenny_signoff_required
  - out_of_sample_holdout_pass_required

Outcomes surface on dashboard as shadow challenger only. Zero grade weight on
scout/dashboard aggregate until ablations demonstrate this composite adds
signal above the simpler components.

## Universe Version

Universe ID, version, membership SHA-256, and membership-as-of date above are
immutable ledger identity. Any change requires a new candidate.
