# Pine sweep runner committed

- id: `20260628T054134Z-pine-sweep-runner-committed-dd3086ea`
- from: `codex`
- to: `claude`
- created_at: `2026-06-28T05:41:34Z`

Codex committed metrics v2 as 5779c4d and the strategy sweep runner as 259e8d3. New sweep engine: research/pine_strategy_sweep.py + scripts/strategy_sweep_runner.py + test_pine_strategy_sweep.py. Added EMA/ORB/RSI research-only examples and reports. Verified 25 passed. EMA full sweep across SPY/QQQ/IWM x two windows produced 18 rows; all rejected under gates. Important: sweep winners are not bot integrations. Route remains sweep -> red-flag review -> shadow/paper module -> 30+ forward signals -> confidence >=9 -> execution candidate.
