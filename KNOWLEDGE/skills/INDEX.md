# Vibe-Trading Skill Library Index
Created: 2026-07-06

Read `KNOWLEDGE/VIBE_TRADING_AGENT_MEMORY.md` first in any new session.

| Skill | Use When |
|---|---|
| `vibe-trading-safety-gates` | Touching orders, execution flags, risk sizing, MAX_CONTRACTS, kill switches, broker APIs |
| `vibe-trading-exit-logic` | Changing profit target, stop loss, ratchet, profit-protect, time exits, capture efficiency |
| `vibe-trading-entry-regime-filters` | Changing entry filters, same-day re-entry rules, trend/VWAP/EMA/ORB/TTM/HMM/PCA/regime gates |
| `vibe-trading-shadow-scanners` | Adding/modifying read-only scanners, shadow loggers, signal registry, promotion gates |
| `vibe-trading-postmortems` | Closed trade postmortems, daily outcome reviews, missed banger reviews, P/L explanations |
| `vibe-trading-dashboard` | Updating generate_dashboard.py, dashboard.html, P/L views, charts, trade tables |
| `vibe-trading-tests` | Running tests, interpreting full-suite failures, avoiding uv+numpy AppLocker issues |
| `vibe-trading-scheduler` | Windows Task Scheduler jobs, PS1 runners, market-hours behavior, scanner automation |
| `vibe-trading-signal-governance` | signal_registry.json, execution audit, signal grades, leaderboard, promotion rules |
| `vibe-trading-options-bot` | IWM/options bot, credit spreads, iron condors, liquidity gate, pending exits |
| `vibe-trading-market-condition-map` | Adaptive market intelligence, trend/chop/volatility labels, GEX, expected move, bias zones |
| `vibe-trading-research-intake` | Evaluating outside repos, X/Twitter ideas, TradingView indicators, quant papers |
| `vibe-trading-claude-codex-handoff` | Writing handoffs, summarizing session state, making next session pick up cleanly |
| `vibe-trading-risk-memory` | Past failure analysis, blowup prevention, current risk state, safety calibration |

## Install Location
Skills live in `KNOWLEDGE/skills/`. Copy to `~/.claude/skills/` for global Claude Code access:
```powershell
Copy-Item KNOWLEDGE\skills\*.md "$env:USERPROFILE\.claude\skills\" -Force
```
