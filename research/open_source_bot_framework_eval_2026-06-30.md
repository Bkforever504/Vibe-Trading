# Open-Source Trading Bot Framework Evaluation - 2026-06-30

Goal: decide whether any major open-source bot framework should replace or strengthen the current Vibe-Trading stack.

Current stack fit:
- Primary broker/execution: Alpaca paper for equities/options.
- Strategy research: local Python backtests, Pine strategy lab, shadow loggers.
- Risk controls: shared execution guard, portfolio kill switch, dashboard.
- Prediction markets: Kalshi/Polymarket research and guarded dry-run/paper workflows.

## Verdict

Do not migrate the main bot stack right now. The current project already has the pieces that matter most for Kenny's path: broker-specific Alpaca execution, options-specific handling, portfolio kill switch, scheduler tasks, dashboard, and paper/shadow evidence gates.

Best use of these frameworks:

1. Lumibot - run a sandbox proof of concept.
2. Freqtrade - borrow crypto research/backtest/optimization patterns.
3. Hummingbot - borrow market-making/arbitrage architecture ideas only.
4. Passivbot - study risk metrics, but do not run live/grid leverage.
5. OctoBot - low-priority crypto automation UI/reference.
6. StockSharp - skip for now due C#/.NET migration cost.

## Framework Ranking

| Rank | Framework | Fit | Recommendation |
| --- | --- | --- | --- |
| 1 | Lumibot | High for Alpaca stocks/options research | Build a sandbox adapter for one shadow strategy only. Do not migrate production yet. |
| 2 | Freqtrade | Medium for crypto research | Use as reference if/when crypto spot/perp strategy research becomes active. |
| 3 | Hummingbot | Medium for crypto market-making/arbitrage | Research-only unless we explicitly pursue CEX/DEX market-making. |
| 4 | Passivbot | Low/medium but risky | Mine risk/backtest ideas. Avoid live grid/perp deployment. |
| 5 | OctoBot | Low | Useful for TradingView/crypto automation concepts, not our core edge. |
| 6 | StockSharp | Low | Powerful, but .NET/C# platform shift is not worth it now. |

## Notes

### Lumibot

Why it matters:
- Python framework for deterministic strategies, AI agents, backtesting, paper trading, and live trading.
- Explicit Alpaca broker support.
- Same-code backtest/paper/live model overlaps with what we want.

Risk:
- Migration could duplicate our custom Alpaca options execution and guard logic.
- AI-agent framing is attractive but must stay behind our confidence and guard system.

Action:
- Create `research/lumibot_eval/` later.
- Port only one non-executing strategy first, ideally QQQ/GLD rotation or Williams %R.
- Compare outputs against our existing shadow logger before trusting it.

### Freqtrade

Why it matters:
- Mature Python crypto bot with backtesting, dry-run/live modes, hyperopt, FreqAI, plotting, data download, and web UI.

Risk:
- Crypto-specific. It does not help Alpaca options directly.
- Hyperopt/ML can encourage overfitting if not run through our PBO/OOS gates.

Action:
- No install needed now.
- Borrow dry-run reporting, hyperopt discipline, and FreqAI feature pipeline ideas.

### Hummingbot

Why it matters:
- Strong open-source crypto market-making/arbitrage framework across CEX/DEX.

Risk:
- Market-making is a different business from our directional/options bots.
- Needs exchange inventory, spread, fee, funding, and tail-risk controls.

Action:
- Research only unless we intentionally build crypto market-making.

### Passivbot

Why it matters:
- Active grid/contrarian market-making bot for crypto perpetuals with optimization/backtest artifacts and risk controls.

Risk:
- Grid/perp strategies can hide tail risk until a trend regime destroys the account.
- Not aligned with "do not rush to live capital."

Action:
- Do not deploy.
- Study risk metrics and artifact reporting only.

### OctoBot

Why it matters:
- Open-source crypto bot with AI, Grid, DCA, and TradingView automation.

Risk:
- Mostly useful if we pivot to crypto automation.
- Some value is product/UI/cloud oriented rather than edge.

Action:
- Low priority. Do not integrate now.

### StockSharp

Why it matters:
- Broad platform supporting many markets, brokers, connectors, backtesting, and strategy infrastructure.

Risk:
- .NET/C# shift would fragment the current Python codebase.
- Too much platform overhead for our immediate Alpaca + shadow-validation path.

Action:
- Skip unless futures/prop-firm execution later demands a full trading platform.

## Next Best Task

Build a Lumibot sandbox only if we want a framework proof:

1. Install Lumibot in an isolated `uv` run, not the main env.
2. Port QQQ/GLD rotation as read-only/paper simulation.
3. Add a comparison report:
   - our logger signal
   - Lumibot signal
   - same input data window
   - same selected asset
4. Keep all execution disabled.

Pass condition:
- Same signal output for at least 10 historical dates and 2 live weekly logs.
- No weakening of portfolio guard/execution guard.

Fail condition:
- Data mismatch, broker incompatibility, or more complexity without better evidence.

Sources:
- Freqtrade docs: https://docs.freqtrade.io/
- Freqtrade FreqAI: https://www.freqtrade.io/en/stable/freqai/
- Freqtrade backtesting/hyperopt: https://www.freqtrade.io/en/stable/backtesting/ and https://www.freqtrade.io/en/stable/hyperopt/
- Hummingbot docs: https://hummingbot.org/docs/
- Hummingbot FAQ: https://hummingbot.org/faq/
- Lumibot docs: https://lumibot.lumiwealth.com/
- Lumibot Alpaca broker docs: https://lumibot.lumiwealth.com/brokers.alpaca.html
- OctoBot GitHub: https://github.com/Drakkar-Software/OctoBot
- Passivbot GitHub: https://github.com/enarjord/passivbot
- StockSharp docs: https://doc.stocksharp.com/
