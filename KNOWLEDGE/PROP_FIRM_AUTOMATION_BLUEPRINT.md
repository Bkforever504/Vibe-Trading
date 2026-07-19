# Prop Firm Automation Blueprint

Last updated: 2026-06-21

Related research:

- `KNOWLEDGE/LAST30DAYS_AI_PROP_TRADING_RESEARCH_2026-06-21.md`
- `KNOWLEDGE/TOPSTEP_PROP_BOT_PLAYBOOK.md`

## Straight answer

Yes, prop firms can create meaningful upside if the strategy has a real edge and obeys the firm's rules. Codex and Claude Code can help build the infrastructure: dashboards, backtests, rule checks, journals, alerts, research, execution guards, and automation. They do not remove trading risk, and they should not be treated as a guaranteed money machine.

The target is not the highest possible win rate. The target is positive expectancy with controlled drawdown and zero rule violations. A strategy can win 80% of the time and still lose money if the average loss is too large.

## Current rule reality

Rules change often, so verify the firm's official rules before funding an account. As of 2026-06-21, official examples show why one generic prop-firm automation setting is not enough:

- Topstep's TopstepX API Access help says advanced traders/developers can build and run automated trading strategies through API access.
- The same Topstep help page says trading activity must originate from a personal device and VPS/VPN/remote servers are prohibited, including running automation on a VPS.
- Topstep's Express Funded Account Rules page also says trading activity can be reviewed by risk/compliance teams for prohibited conduct.

This is why the bot must treat unknown or unverified rules as blocked in prop/live mode.

## Required confidence score before scaling

Do not scale into prop-firm evaluations unless the system scores 90/100 or higher on this checklist.

| Area | Points | Requirement |
| --- | ---: | --- |
| Rule compliance | 20 | Firm-specific rule file exists and bot blocks trades that would violate daily loss, trailing drawdown, max contracts, news rules, copy-trading rules, and automation limits. |
| Evidence sample | 20 | 50+ closed paper trades or high-quality replay/backtest trades using realistic fills, spreads, slippage, and fees. |
| Expectancy | 15 | Profit factor 1.3+ and positive average expectancy after fees/slippage. |
| Drawdown control | 15 | Max drawdown fits inside the prop firm's loss rules with a 30-50% buffer. |
| Execution safety | 10 | Kill switch, max daily loss guard, max trade count, max open risk, and no martingale behavior. |
| Journaling | 10 | Every signal, order, fill, exit, and rule decision is logged. |
| Operator workflow | 10 | Daily preflight and end-of-day review are simple enough to follow every trading day. |

## Automation stance

Use three modes:

1. Shadow mode
   - Bot produces signals and logs what it would have done.
   - No orders.
   - Use this for new strategies and AI-assisted decisions.

2. Paper mode
   - Bot places paper trades only.
   - Dashboard tracks win rate, profit factor, drawdown, and rule-risk score.
   - Use this until the confidence score is 90+.

3. Prop/live mode
   - Only allowed after a firm-specific rules module is written.
   - AI can assist with analysis, but final orders must pass deterministic rule gates.
   - Start with the smallest allowed size.

## Bot architecture

The prop-firm version should be:

```mermaid
flowchart LR
  A["Market data"] --> B["Strategy signals"]
  B --> C["AI commentary / ranking"]
  C --> D["Deterministic risk gate"]
  D --> E["Firm rule gate"]
  E --> F["Order execution"]
  F --> G["Journal + dashboard"]
  G --> H["Daily review"]
```

Important: the AI layer should rank or explain signals. It should not bypass the deterministic risk gate.

## Firm-specific rules module

Create one JSON file per firm before connecting any real prop account:

```json
{
  "firm": "Example Firm",
  "account_size": 50000,
  "max_daily_loss": 1000,
  "max_trailing_drawdown": 2500,
  "max_contracts": 5,
  "news_trading_allowed": false,
  "overnight_holds_allowed": false,
  "automation_allowed": "verify_current_rules",
  "copy_trading_allowed": "verify_current_rules",
  "consistency_rule": "verify_current_rules"
}
```

The bot should block a trade when any field is unknown and the account is not paper.

## Strategy direction

Best starting point for prop firms:

- Futures or highly liquid index products, not illiquid options.
- Defined session windows.
- Small fixed risk per trade.
- Stop-loss attached immediately.
- Daily max loss lower than the firm's limit.
- No averaging down.
- No martingale.
- No overnight exposure unless the firm explicitly allows it.

Current Alpaca options bot is useful for research and paper learning, but it is not directly a prop-firm bot yet because most prop firms focus on futures/FX/CFDs and have separate platform/rule constraints.

## Next build items

1. Add a `rules/prop_firms/` folder with JSON rule profiles.
2. Add a `prop_rule_gate.py` module that returns allow/block/reason before any order.
3. Add shadow-mode AI signal ranking that writes to the dashboard but cannot trade.
4. Add realistic backtest/replay with slippage, commissions, spreads, and max drawdown.
5. Add daily preflight report: account status, max loss remaining, news lockouts, open exposure, and allowed size.
6. Add a manual-reset kill switch file that blocks trading after major drawdown or abnormal behavior.

## Implemented Safety Layer

Implemented on 2026-06-21:

- `strategies/risk_kill_switch.py`
  - Writes/reads `~\.vibe-trading\MANUAL_RESET_REQUIRED.json`.
  - Blocks new orders when the manual-reset file exists.
  - Can create the block file when daily loss or max drawdown thresholds are breached.

- `strategies/shadow_ai_signals.py`
  - Writes `~\.vibe-trading\shadow-ai-signals.jsonl`.
  - Every record is marked `mode: shadow_only` and `executable: false`.
  - This is for AI ranking/commentary only, not order authority.

- `strategies/iwm_options_bot.py`
  - `_post_order_with_retry()` now refuses orders when manual reset is required.

- `strategies/flip_bot.py`
  - `_submit()` now refuses orders when manual reset is required.

- `strategies/prop_rule_gate.py`
  - Evaluates proposed prop-firm trades against machine-readable JSON rule profiles.
  - Blocks unknown/unverified rules when `unknown_rules_block` is true.
  - Blocks automation-prohibited firms, VPS/local-device violations, daily-loss breaches, trailing-drawdown breaches, max-contract breaches, and consistency-rule breaches.

- `rules/prop_firms/`
  - `topstep_topstepx_api.json`
  - `apex_conservative.json`
  - `tradeify_conservative.json`
  - `README.md`

Verification:

- `uv run --no-project --with pytest python -m pytest agent/tests/test_strategy_safety_layers.py -q`
- `python -m py_compile strategies\risk_kill_switch.py strategies\shadow_ai_signals.py strategies\iwm_options_bot.py strategies\flip_bot.py strategies\trading_dashboard.py`

Confidence interpretation:

- Compliance/rule-gate confidence can be high when rules are complete or safely blocked by default.
- Strategy-profit confidence is still not high until the bot has 50+ closed paper trades or a realistic replay/backtest showing positive expectancy after fees/slippage.
- Never raise a strategy to prop/live mode just because the compliance gate passes.
