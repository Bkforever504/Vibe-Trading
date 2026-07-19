# YouTube / Social Strategy Intake Template

Use this template for any strategy found on YouTube, X, Reddit, Discord, TradingView, TikTok, or a course clip. The goal is to convert a claim into a testable strategy without letting a good story bypass the Vibe-Trading evidence gates.

## 1. Source

- Intake ID:
- Date captured:
- Source URL:
- Platform:
- Trader / channel / handle:
- Market discussed:
- Ticker(s) or asset class:
- Timeframe(s):
- Claimed return / win rate / Sharpe:
- Is the claim independently audited? `yes/no/unknown`
- Notes on sponsorship, course sale, broker referral, or affiliate link:

## 2. Exact Rules From Source

Only write rules actually stated by the trader. Do not fill gaps with guesses.

### Bias / Regime

- Higher-timeframe bias rule:
- Market regime filter:
- Volatility / VIX / news filter:
- Time-of-day or session filter:

### Long Entry

- Required condition 1:
- Required condition 2:
- Required condition 3:

### Short Entry

- Required condition 1:
- Required condition 2:
- Required condition 3:

### Avoid Trade

- Red flag 1:
- Red flag 2:
- Red flag 3:

### Stop / Risk

- Initial stop:
- Position sizing:
- Max daily loss:
- Max trades per day:
- Invalid setup condition:

### Exit / Take Profit

- Target 1:
- Target 2:
- Trailing stop:
- Time stop:
- End-of-day / hard close:

## 3. Ambiguity Checklist

Every unchecked item must be resolved before backtesting.

- [ ] What counts as a candle close confirmation?
- [ ] Are entries allowed intrabar or only after close?
- [ ] What happens on gap opens?
- [ ] What happens when stop and target hit on the same candle?
- [ ] How is spread/slippage modeled?
- [ ] Are commissions included?
- [ ] Are shorts allowed in the intended account?
- [ ] Are options contracts selected by delta, strike distance, premium, or liquidity?
- [ ] Is the data adjusted/unadjusted?
- [ ] Does the strategy require paid/protected indicators?
- [ ] Are holidays, FOMC, CPI, or earnings filtered?

## 4. Repaint / Lookahead Risk

- Uses higher-timeframe data? `yes/no`
- HTF data offset by at least one completed bar? `yes/no/n/a`
- Uses pivots/fractals that need future bars? `yes/no`
- Uses `barmerge.lookahead_on` or equivalent? `yes/no`
- Uses TradingView strategy tester settings that can inflate fills? `yes/no`
- Repaint scan result:
- Notes:

## 5. Implementation Status

- Pine strategy file:
- Pine compile status:
- Python port file:
- Backtester used:
- Data source:
- Asset universe:
- Date range:
- In-sample range:
- Out-of-sample range:

## 6. Backtest Gates

Minimum gates before any shadow logger:

- Trade count >= 30:
- Profit factor >= 1.5:
- OOS profit factor >= 1.2 and <= 10 unless explained:
- Walk-forward pass rate >= 0.55:
- PBO <= 0.40:
- Max drawdown <= strategy-specific gate:
- Sharpe / Sortino:
- Includes slippage and commissions:
- Uses one-bar signal shift or equivalent no-lookahead enforcement:

## 7. Forward-Test Gate

- Shadow logger file:
- Log path:
- First live log date:
- Minimum days before review: `30`
- Minimum entry signals before review: `10`
- Current signal count:
- Current hypothetical P&L:
- Current win rate:
- Current max drawdown:
- Review status: `blocked/logging/review_ready/rejected/paper_candidate`

## 8. Promotion Decision

- Confidence score:
- Main reason to promote or reject:
- Execution mode allowed:
  - [ ] context-only
  - [ ] shadow-only
  - [ ] paper
  - [ ] live
- Required guard additions before execution:
- Final decision:

## Rule

No strategy from social media gets execution just because the source is convincing. It must pass the same Vibe-Trading sequence:

`source -> rules -> ambiguity cleanup -> repaint scan -> Python port -> OOS/WF/PBO -> shadow logger -> 30-day review -> paper -> live only after earned confidence`
