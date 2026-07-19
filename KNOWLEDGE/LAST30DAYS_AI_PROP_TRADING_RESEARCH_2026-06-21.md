# Last 30 Days Research: AI Trading Bots, Prop Firms, and Automation

Date: 2026-06-21

Research source:

- Engine: `last30days` v3.3.2
- Query: `AI trading bots for prop firms and automated day trading`
- Saved raw file: `C:\Users\kenne\Documents\Last30Days\ai-trading-bots-for-prop-firms-and-automated-day-trading-raw-vibe-trading-prop-bot-youtube.md`
- Coverage: 26 Reddit threads, 14 YouTube videos, 1,503,851 YouTube views, 8/14 videos with transcripts
- Missing: X/Twitter, because no X browser cookie/auth token/xAI key is configured for the research engine

Supplemental X search:

- Chrome has X open, but the Codex Chrome-control connection failed in this session, and the `last30days` engine still reports `x_backend: null`.
- Public web search surfaced recent X snippets, but not full authenticated X results. Treat these as lower-confidence directional signals, not complete X coverage.

Second X-enabled attempt:

- After saving `XAI_API_KEY`, `last30days --diagnose` detected `xai: true` and `x_backend: xai`.
- The research run still returned `X: HTTP 403: Forbidden`.
- Interpretation: the key is present, but the xAI account/key likely needs billing credits, API access, model access, or a different permission state before X search works.
- Saved raw file: `C:\Users\kenne\Documents\Last30Days\best-easiest-automated-trading-strategy-ai-bots-prop-firms-market-profits-raw-vibe-trading-x-enabled.md`
- Coverage from this second run: 27 Reddit threads, 16 YouTube videos, 4,402,765 YouTube views, 7/16 videos with transcripts.

## What Traders Are Saying

The strongest message is not "let AI trade by itself." The strongest message is: use AI to build, test, explain, journal, and enforce rules, while deterministic risk gates control execution.

The Reddit signal is very skeptical of easy-profit claims. Recent high-engagement threads on r/Daytrading and r/algotrading lean toward discipline, long sample sizes, emotional control, replay work, and risk management. The r/algotrading thread "Letting AI grow $300" is directly relevant, but it should be treated as a prototype idea, not proof of a durable edge.

The YouTube signal is more promotional, but still useful. The best technical ideas came from "How To Actually Build a Trading Bot With Claude Code (Fully Automated)" by AI Pathways. The strongest ideas from that transcript were:

- Use market-regime detection instead of a single indicator trigger.
- Compare against a baseline such as a 200-day SMA trend system.
- Use out-of-sample evaluation.
- Cut size after a bad day.
- Stop the bot completely after major drawdown and require manual reset.

Prop-firm content repeatedly talks about consistency rules, drawdown rules, account selection, and payout rules. PB Blake's prop-firm video specifically mentioned starting smaller and avoiding one-day profit concentration, including a 35% consistency-rule example.

## Practical Takeaways For Kenny's Bot

1. Win rate cannot be the north star.
   - Track profit factor, expectancy, average win/loss, max drawdown, daily loss, and rule violations.
   - A high-win-rate premium/options strategy can still lose if one loss wipes out many winners.

2. AI should not be the execution authority yet.
   - AI can rank setups, summarize context, explain why a signal is weak, and generate a trade note.
   - The order decision must pass deterministic gates: market hours, max risk, max daily loss, max open trades, liquidity, spread width, volatility, news, and firm rules.

3. Prop-firm mode must be a separate system.
   - Current Alpaca options bot is useful for research and paper trading.
   - A prop-firm version likely needs futures-focused logic, firm-specific rules, and platform-specific execution.
   - Do not connect a prop account until the bot has a rule profile for that firm.

4. The system needs a hard "manual reset" kill switch.
   - After a configured drawdown threshold, the bot should write a block file and refuse to trade until Kenny manually removes it.
   - This came up strongly in the AI Pathways bot transcript and fits prop-firm risk.

5. Research and backtesting need to become a repeatable pipeline.
   - Every new strategy idea should get a confidence score before it reaches paper mode.
   - Every paper strategy should get at least 50 closed trades or a realistic replay/backtest before scaling.

## Supplemental X Signals

Public X search found recent posts around:

- Connecting Claude Code or Codex to trading terminals to generate bots.
- AI agents reading charts or TradingView-style signals and firing trades when criteria are met.
- Traders using prop-firm-like constraints such as 50k starting balance, max risk per trade, and Topstep-style rules.
- Claims about agentic trading and AI-connected brokerage workflows.

Interpretation:

- X is more hype-heavy than Reddit. The most useful X signal is product direction: traders want AI-connected terminals, chart-reading agents, and bot builders.
- For Kenny's system, do not copy the "agent fires trades" framing yet. Use it as product inspiration for the dashboard and shadow AI layer.
- The credible version is: AI proposes and explains, risk gate approves or blocks, dashboard records everything.

## New Build Requirements

Add these to the trading bot roadmap:

1. `shadow_ai_signals.py`
   - Reads market context and existing strategy signals.
   - Calls an LLM only for commentary/ranking.
   - Writes JSONL decisions.
   - Does not place orders.

2. `risk_kill_switch.py`
   - Blocks trading after max daily loss, max drawdown, or abnormal behavior.
   - Writes a manual-reset block file.
   - Refuses to trade when the block file exists.

3. `rules/prop_firms/*.json`
   - One profile per firm.
   - Unknown rule fields block prop/live execution.

4. Dashboard upgrades
   - Add profit factor and expectancy once closed-trade matching exists.
   - Add strategy-by-strategy cards.
   - Add drawdown chart.
   - Add "prop readiness" score.

5. Backtest/replay
   - Include fees, slippage, spreads, partial fills, and realistic fill assumptions.
   - Compare against a baseline.
   - Separate in-sample from out-of-sample periods.

## Confidence Score After Research

Current confidence for scaling to real prop-firm automation: 4/10.

Reason:

- We have promising architecture ideas.
- We do not yet have enough closed trade data.
- We do not yet have firm-specific rule gates.
- We do not yet have a futures prop-firm execution stack.
- The current dashboard is read-only, which is correct, but not enough for scaling.

Target before prop-firm execution: 9/10 or higher.

## Immediate Next Step

Build the shadow AI signal layer and kill-switch layer first. Do not give AI order authority yet.

## Best/Easiest Money Path Based On Research

The easiest realistic automated path is not fully autonomous AI picking trades. The easiest realistic path is:

1. Pick one liquid market and one setup family.
   - For prop-firm direction, this likely means futures such as NQ/MNQ or ES/MES.
   - For the current Alpaca bot, keep IWM options paper-only while proving the analytics stack.

2. Use rule-based setups, not AI discretion.
   - Opening range breakout, VWAP/volume/order-flow confirmation, or defined premium-selling setups are easier to test than broad discretionary chart reading.
   - AI can summarize context and rank setups, but it should not invent trades.

3. Automate risk first.
   - Max daily loss.
   - Max drawdown.
   - Max open trades.
   - Max contracts.
   - News/session lockouts.
   - Manual-reset kill switch.

4. Measure before scaling.
   - 50+ closed paper trades or a realistic replay/backtest.
   - Profit factor above 1.3.
   - Positive expectancy after fees/slippage.
   - Drawdown that leaves 30-50% buffer under prop-firm rules.

5. Only then automate execution.
   - Start with paper mode.
   - Move to shadow prop mode.
   - Move to smallest-size prop/live mode only after the rule gate is complete.

Current recommendation:

- Build shadow AI signal layer and kill switch now.
- Do not chase "easy money" bot claims.
- The first monetizable goal is a reliable automated risk/compliance/dashboard system. Profits come after the system proves edge.
