# MNQ Decision Process Research + Filters - 2026-06-22

## Why This Exists

Kenny asked why we cannot copy profitable MNQ traders directly. The answer is that we can copy their decision process only after it is translated into testable rules. Screenshots are not enough. The repeatable parts from current research are:

- Tight entry windows
- VWAP directional alignment
- Structural pullback instead of raw ORB breakout
- Daily or higher-timeframe trend context
- EMA or momentum alignment
- Volume/participation confirmation
- Topstep consistency-rule awareness
- Skipping marginal setups

## Research Run

Ran `/last30days` style research with:

Topic:
`MNQ prop firm ORB VWAP SMC execution rules`

Raw result:
`C:\Users\kenne\Documents\Last30Days\mnq-prop-firm-orb-vwap-smc-execution-rules-raw-codex-mnq-prop-rules.md`

The engine returned thin recent evidence because public platform access was limited:
- Reddit only
- 1 thread from `r/PropFirmTester`
- YouTube unavailable without `yt-dlp`
- X unavailable / blocked

Manual web research still matched the same pattern Kenny's prior research found: the edge is not raw ORB. It is ORB + VWAP + pullback-to-structure + strict risk selection.

## What Codex Implemented

File:
`strategies/topstep_replay_backtester.py`

Added config fields:
- `session_entry_start_hour`
- `session_entry_start_minute`
- `require_ema_confirm`
- `ema_period`
- `require_live_vwap_confirm`
- `require_volume_confirm`
- `volume_lookback`
- `min_volume_ratio`

Added filters:
- Entry start gate: blocks trades before configured start time.
- EMA confirmation: long only above EMA, short only below EMA at actual entry candle.
- Live VWAP confirmation: long only above current session VWAP, short only below it at actual entry candle.
- Volume confirmation: entry volume must exceed average prior volume by configured ratio.

Added CLI flags:
- `--start-hour`
- `--start-minute`
- `--require-ema-confirm`
- `--ema-period`
- `--require-live-vwap-confirm`
- `--require-volume-confirm`
- `--volume-lookback`
- `--min-volume-ratio`

Tests added:
- Session start blocks early trigger.
- EMA confluence blocks pullback entry below EMA.
- Volume confluence blocks low-volume trigger.

Verification:

```powershell
uv run --no-project --with pytest python -m pytest agent/tests/test_topstep_replay_backtester.py agent/tests/test_topstep_prop_bot.py agent/tests/test_strategy_safety_layers.py -q
```

Result:

```text
44 passed
```

## OOS Results On Current 1H MNQ Dataset

Baseline with daily trend filter:
- Test P&L: `$24.00`
- Win rate: `25.0%`
- PF: `1.09`
- Expectancy: `$3.00/trade`
- Max drawdown: `$156.00`
- Trades: `8`
- Consistency violations: `3`

Daily trend + EMA 20:
- Same test result as baseline.
- On 1-hour data, EMA 20 did not filter additional test trades.

Daily trend + live VWAP:
- Same test result as baseline.
- On 1-hour data, live VWAP did not filter additional test trades.

Daily trend + volume confirmation:
- Train: 1 trade, loss
- Test: 0 trades
- Verdict: too restrictive on current 1-hour data.

## Verdict

The new filters make the system more faithful to the trader decision process, but they do not yet create a strong out-of-sample edge on 1-hour MNQ data.

The likely missing layer is not another generic indicator. It is SMC/key-level execution:

- Prior day high/low proximity
- Premarket high/low proximity
- Break of structure before pullback
- Pullback into order-block candle body
- Reject trades directly into opposing liquidity
- Trade management: partial at 1R, stop to breakeven, runner to 2R

Updated confidence:
- Backtester reliability: `9.0/10`
- Strategy realism: `5.5/10`
- Strategy profit confidence: `4.8/10`
- Combine-readiness: `2.0/10`

## Claude Code Handoff

Next task for Claude:

Build the SMC/key-level layer in the replay backtester.

Priority order:

1. Add prior-day high/low and premarket high/low annotations per trading day.
2. Add `require_key_level_proximity`:
   - Long pullbacks must be near OR high, VWAP, prior high, or premarket high.
   - Short pullbacks must be near OR low, VWAP, prior low, or premarket low.
3. Add break-of-structure confirmation:
   - Long requires higher high after OR breakout before pullback entry.
   - Short requires lower low after OR breakout before pullback entry.
4. Add optional trade management model:
   - Take partial at 1R.
   - Move stop to breakeven after 1R.
   - Let remainder target 2R.
5. Run OOS validation sorted by `consistency_adjusted_score`, not raw expectancy.

Do not connect live orders. Paper/replay only.
