# Novel Information Edge Results - 2026-08-04

## Decision

No track qualifies for strategy promotion or production authority.

| Track | Evidence | Decision |
| --- | --- | --- |
| Option-chain microstructure | 2 resolved OPRA CBBO lifecycles; both profitable in the earlier replay | Insufficient: 30 required |
| Signed order flow | 22,080 one-minute windows; frozen absorption conjunction produced zero candidates | Reject frozen rule |
| Cross-asset lead-lag | 61 overlapping sessions and 265-609 development trades per leader | Reject all five hypotheses |
| Event surprises | No local source with consensus-as-known and first-release vintage | Data blocked |

## Cross-asset development results

| Leader | Relation | Trades | Base expectancy | Stress expectancy | Stress PF |
| --- | --- | ---: | ---: | ---: | ---: |
| SPY | Same | 292 | -$2.73 | -$7.71 | 0.54 |
| QQQ | Same | 293 | -$4.42 | -$9.40 | 0.47 |
| HYG | Same | 290 | -$3.85 | -$8.83 | 0.46 |
| TLT | Opposite | 265 | -$0.28 | -$5.26 | 0.65 |
| VIX | Opposite | 609 | -$3.80 | -$8.78 | 0.42 |

The 19-session cross-asset holdout remains sealed because no development
hypothesis survived. The five failures increase the permanent effective
multiple-testing denominator from 515 to 520.

## Operational correction

`research/options_nbbo_curriculum.py` incorrectly defaulted its quote input to
the candidate log. The default now targets the downloaded Databento OPRA CBBO
JSONL. A regression test prevents recurrence. The corrected replay resolves
2/2 lifecycles but still fails the minimum-sample review gate.

## Event-source finding

Official BLS/FRED/ALFRED sources can establish releases and revisions, but do
not provide the historical analyst consensus needed to measure surprise.
Trading Economics documents point-in-time consensus history as a licensed
capability. Unversioned public calendar datasets are diagnostics only and
cannot establish what was known before release.

No orders were submitted. None of these research artifacts can alter entries,
sizing, risk limits, or execution state.

