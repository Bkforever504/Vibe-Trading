# Strategy Intake Queue

Social/YouTube/X/GitHub strategy ideas captured here before any research time is spent.

## Philosophy

Social media = idea source. TradingView = visual sanity check. Python = statistical gate. Shadow logging = live evidence gate. Execution = last step, never default.

## Gate Stack (every candidate must pass all)

1. Rule clarity — entry/exit/stop must be 100% unambiguous before coding
2. trades >= 20 in backtest window
3. OOS PF > 1.0
4. WF >= 0.60
5. PBO < 0.50
6. Max DD < 25%
7. 30-day forward-test log + 10 real entry signals

## Pipeline Stages

```
intake (this file)
  → pine_status: needs_scan / not_started / done
  → python_status: not_started / in_progress / done
  → backtest_status: pending / running / done
  → decision: pending / paper_candidate / rejected
```

## Reject Early If

- Vague ICT/SMC rules without objective price levels
- Screenshot-only "insane PF" with no trade list
- Strategy relies on protected indicator (can't see rule output)
- Repaint or lookahead confirmed by scanner
- Uses leveraged ETF (3x) without explicit size plan
- Published edge likely arbitraged away (post-publication decay check)
- Signals highly correlated with an existing shadow candidate

## Sources Priority

- GitHub repos with documented PF + trade counts (scan pipeline ready)
- QuantifiedStrategies.com (exact rules, backtested, documented)
- Quantpedia (academic, reproducible)
- YouTube channels with exact rule walkthroughs (not vague setups)

## Avoid

- Viral "I turned $1k to $100k" TikTok
- ICT/SMC vague concepts without objective trigger
- Any strategy requiring manual chart reading as entry condition

## Files

- `strategy_queue.json` — intake items with full schema
- `README.md` — this file
