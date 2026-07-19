# Investing Algorithm Framework Probe

Read-only evaluation of ideas from:

https://github.com/coding-kitties/investing-algorithm-framework

## Verdict

Use as a sandbox/reporting pattern, not as a replacement for Vibe-Trading execution.

The repo's useful ideas are:

- vectorized backtest first
- event-driven validation second
- ranked metrics across strategies
- Monte Carlo/permutation robustness checks
- explicit slippage, fees, cooldowns, stop-loss, and take-profit rules

## Current Probe

`scripts/iaf_qqq_gld_probe.py`

The first target is the existing QQQ/GLD rotation shadow candidate. The probe:

1. Fetches QQQ/GLD close data through the shared market data layer.
2. Recomputes the 40-trading-day relative momentum signal.
3. Produces simple framework-style metrics.
4. Compares the result with the latest `data/qqq_gld_shadow_log.jsonl` row.
5. Writes a JSON report to `~/.vibe-trading/reports/iaf-qqq-gld-probe.json`.

## Safety

- `execution_enabled=false`
- no Alpaca order calls
- no Kalshi order calls
- no scheduler by default
- cannot replace the existing guard stack

Promotion requires a replay match against existing shadow logs before expanding to other strategy candidates.
