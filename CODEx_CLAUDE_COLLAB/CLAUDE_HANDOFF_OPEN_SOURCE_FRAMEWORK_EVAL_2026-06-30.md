# Claude Handoff - Open-Source Bot Framework Evaluation

Date: 2026-06-30
Repo: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

## User Ask

Kenny asked whether these open-source bot frameworks can help us:
- Freqtrade
- Hummingbot
- Lumibot
- OctoBot
- Passivbot
- StockSharp

## Codex Evaluation

Full note written:

`research/open_source_bot_framework_eval_2026-06-30.md`

## Decision

Do not migrate the main bot stack.

Reason:
- Current stack already has Alpaca-specific options/equity execution, shadow loggers, Pine strategy lab, execution guard, portfolio kill switch, dashboard, and Task Scheduler wiring.
- Framework migration would add risk before it adds edge.

## Ranking

1. `Lumibot` - best fit for a sandbox proof because it supports Python, Alpaca, backtesting, paper/live flow, and multi-asset strategy development.
2. `Freqtrade` - useful reference for crypto backtesting, hyperopt, FreqAI, dry-run reporting. Not useful for Alpaca options execution.
3. `Hummingbot` - useful only if we intentionally pursue crypto market-making/arbitrage.
4. `Passivbot` - study risk/reporting, but do not deploy grid/perp leverage.
5. `OctoBot` - low-priority crypto automation/UI reference.
6. `StockSharp` - skip for now due .NET/C# platform shift.

## Recommended Next Task

If Kenny wants action, build a Lumibot sandbox only:

1. Create `research/lumibot_eval/`.
2. Use isolated `uv run --no-project --with lumibot ...`.
3. Port exactly one strategy first:
   - preferred: QQQ/GLD rotation, because it is weekly, simple, and already has a shadow logger.
4. Build a comparison report:
   - current Vibe-Trading signal
   - Lumibot signal
   - same historical dates
   - same data window
   - selected asset match/mismatch
5. Keep all execution disabled.

Pass gate:
- Same signal output for at least 10 historical dates and 2 live weekly logs.
- No weakening of execution guard or portfolio kill switch.

Fail gate:
- Data mismatch, broker mismatch, options incompatibility, or extra complexity without better evidence.

## Do Not Do

- Do not install all frameworks into the main env.
- Do not migrate Alpaca bots.
- Do not run Passivbot live.
- Do not enable Hummingbot market-making.
- Do not loosen confidence gates because a framework has attractive backtest output.

## Sources

- Freqtrade docs: https://docs.freqtrade.io/
- Freqtrade FreqAI: https://www.freqtrade.io/en/stable/freqai/
- Hummingbot docs: https://hummingbot.org/docs/
- Lumibot docs: https://lumibot.lumiwealth.com/
- Lumibot Alpaca broker docs: https://lumibot.lumiwealth.com/brokers.alpaca.html
- OctoBot GitHub: https://github.com/Drakkar-Software/OctoBot
- Passivbot GitHub: https://github.com/enarjord/passivbot
- StockSharp docs: https://doc.stocksharp.com/
