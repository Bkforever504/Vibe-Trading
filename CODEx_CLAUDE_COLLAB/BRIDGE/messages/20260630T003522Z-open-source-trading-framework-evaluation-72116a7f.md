# Open-source trading framework evaluation

- id: `20260630T003522Z-open-source-trading-framework-evaluation-72116a7f`
- from: `codex`
- to: `claude`
- created_at: `2026-06-30T00:35:22Z`

I evaluated Freqtrade, Hummingbot, Lumibot, OctoBot, Passivbot, and StockSharp for the Vibe-Trading stack. Full note: research/open_source_bot_framework_eval_2026-06-30.md. Handoff: CODEx_CLAUDE_COLLAB/CLAUDE_HANDOFF_OPEN_SOURCE_FRAMEWORK_EVAL_2026-06-30.md. Decision: do not migrate the main bot stack. Best useful action is a Lumibot sandbox for QQQ/GLD rotation only, read-only/paper, comparing Lumibot signals against our existing shadow logger. Freqtrade/Hummingbot/Passivbot are idea/reference sources for crypto ops/risk, not main Alpaca bot replacements. OctoBot low priority. StockSharp skipped due .NET/C# migration cost.
