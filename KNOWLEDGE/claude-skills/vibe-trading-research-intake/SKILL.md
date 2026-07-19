---
name: vibe-trading-research-intake
description: Use when evaluating outside repos, X/Twitter ideas, TradingView indicators, quant papers, or social strategy claims before coding.
---

# Vibe-Trading Research Intake

## Intake File
`research/signal_registry.json` — all evaluated signals with status and notes.
`research/repo_eval_*.md` — per-repo evaluation notes.

## Intake Process
1. Read or test the idea in isolation (no code changes to live bot)
2. Write evaluation notes in `research/repo_eval_<name>_<date>.md`
3. Add entry to `signal_registry.json` with `type: "research_intake"`, `execution_enabled: false`
4. Rate signal on 4 criteria: edge clarity, implementation complexity, data availability, fit with current stack
5. If promising: build as read-only shadow scanner, log for 30 days, then review

## What Gets Rejected Immediately
- Strategies requiring paid real-time data feeds (Tradovate, Bloomberg, etc.)
- Strategies that require HFT-level latency
- Social signal wired directly to orders with no evidence period
- Crypto strategies until Flip Bot clears 30-day gate (deferred)
- Any idea that requires disabling existing safety gates

## Free Data Sources (approved)
- Alpaca IEX feed (paper account)
- yfinance (delayed, for research)
- Polymarket API (public, on-chain)
- Kalshi public profiles (limited — top traders hide history)
- SEC EDGAR (insider buying)

## Fable 5 / Claude Context
Fable 5 (Claude Mythos-class, 1M context, released June 2026): high cost ($10/$50 per M tokens). Use for complex multi-step analysis only. Current stack works well with Claude Sonnet + Codex without Fable 5.

## Evaluation Template
```
Idea: <name>
Source: <X post / repo / paper>
Edge: <what inefficiency it exploits>
Data needed: <free/paid/API>
Implementation: <simple/medium/complex>
Verdict: intake_shadow / reject / defer
Reason: <one line>
```

## Red Flags
- Backtest-only strategy with no forward-test plan
- Strategy where "edge" is survivorship bias (only shows winners)
- Indicator that requires future data (`df.shift(-1)`) — caught by `strategy_leak_audit.py`
