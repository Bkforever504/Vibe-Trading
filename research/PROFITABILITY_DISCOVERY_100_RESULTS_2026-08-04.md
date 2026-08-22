# Profitability Discovery 100 Results - 2026-08-04

## Decision

No candidate survived development. Selection and final holdouts remain sealed. No
strategy, risk limit, sizing rule, execution gate, or order path was changed.

## Frozen protocol

- Registry: 100 unique trials across 10 causal MES intraday strategy families
- Registry SHA-256: `d0311c50bf5631697c8f41735cb4ddae5293c7e99ea01ce2677c0479dee227db`
- Data: 1,148 sessions, with 803 development, 172 sealed selection, and 173 sealed final sessions
- Execution model: adverse-first same-bar resolution, one trade per session, explicit costs
- Stress test: doubled modeled costs
- Multiple-testing count: 515 effective attempts
- Bonferroni alpha: `0.00009709`
- Minimum development observations: 30 trades

## Best doubled-cost result by family

| Family | Trial | Trades | Expectancy | Profit factor | Result |
| --- | --- | ---: | ---: | ---: | --- |
| ORB breakout | DISC100-010 | 664 | -$4.98 | 0.79 | Reject |
| ORB failed break | DISC100-016 | 265 | -$8.94 | 0.52 | Reject |
| Prior-day breakout | DISC100-027 | 527 | -$10.55 | 0.54 | Reject |
| Prior-day reclaim | DISC100-038 | 164 | -$7.77 | 0.71 | Reject |
| VWAP trend pullback | DISC100-049 | 217 | -$5.66 | 0.77 | Reject |
| VWAP deviation fade | DISC100-051 | 802 | -$10.73 | 0.40 | Reject |
| Opening impulse continuation | DISC100-070 | 502 | -$6.38 | 0.76 | Reject |
| Opening impulse reversal | DISC100-075 | 593 | -$10.25 | 0.65 | Reject |
| Compression breakout | DISC100-084 | 9 | +$9.76 | 1.51 | Reject: insufficient sample and significance |
| Range-expansion reversal | DISC100-100 | 24 | -$5.27 | 0.82 | Reject |

## Interpretation

The experiment rules out promotion of these parameterized price-action families;
it does not prove that no market edge exists. The only positive doubled-cost result
had nine trades and a one-sided p-value of `0.2934`, far above the corrected
threshold. Opening a holdout or deploying it would be selection bias.

Another large search over the same OHLCV patterns is unlikely to add useful
information. The next research cycle should require genuinely new point-in-time
features, such as option-chain microstructure, signed order flow, cross-asset
lead-lag, or timestamped event-surprise data. Each source must first pass coverage,
latency, revision, and executable-price audits before strategy testing.

## Artifacts

- `research/edge_trials/profitability_discovery_100_registry_2026-08-04.json`
- `data/profitability_discovery_100_results.json`
- `research/edge_trials/profitability_discovery_100_ledger_import_2026-08-04.json`
- `data/edge_trial_ledger.jsonl`

