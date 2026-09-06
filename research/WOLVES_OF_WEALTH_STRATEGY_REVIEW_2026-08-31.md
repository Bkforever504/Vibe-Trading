# Wolves of Wealth / Mr. Banks strategy review

Status: research intake only. `execution_enabled=false`; no rank or alert effect.

## Source quality

The supplied screenshots identify Mr. Banks (`@RealJGBanks`), Wolves of Wealth, and two videos: [Best Day Trading Strategy Small Accounts | FULL BREAKDOWN](https://www.youtube.com/watch?v=TucGJT3lgbE) and [HOW TO ENTER AND EXIT TRADES | SECRETS REVEALED](https://www.youtube.com/watch?v=0ip-uj6q_LY). Direct X/YouTube pages did not return a verifiable transcript in this environment, so this review does not claim to reproduce the videos. The detailed rules below are transcribed from a public mirror of the author's BBR strategy thread: [BBR strategy thread mirror](https://en.rattibha.com/thread/1736925002073505835). The mirror is secondary evidence, not an audited performance record.

## Recovered rule set

- Map prior-market levels: previous-month high/low (PMH/PML), previous-day high/low (YDH/YDL), and major higher-timeframe support/resistance.
- Use level location for directional bias: above PMH/YDH is bullish context; below PML/YDL is bearish context. A level break is a context filter, not by itself a trade.
- Use the 200 EMA as a broad regime filter and the 13/48 EMA cross as trend direction.
- Use the 8/13/21/48 EMA ladder for entry/trend-riding and a full-body close/hold through the selected EMA as an exit/defense rule.
- The examples use 5-minute bars (with 2-minute bars mentioned for faster entries); higher timeframes are intended for swing context.
- The strongest stated confluence is a break/hold above PMH and YDH while price is above the 200 EMA and the lower EMA set is crossed upward. The bearish case is the symmetric opposite.

## What is genuinely new for our system

Our existing taxonomy contains level sweeps/reclaims and EMA proxies, but not this exact conjunction as a named family. The candidate is therefore registered as `wolves_bbr_ema_level_confluence` and remains untested. The exact first-break versus close-confirmation rule, retest requirement, stop placement, target, and EMA chosen for exit are not recoverable from the screenshots alone.

## Safe test plan

1. Freeze two separate families: (a) level-bias + break/retest without EMA filters, and (b) the full BBR conjunction. This prevents attributing any result to an unisolated bundle.
2. Preregister SPY and QQQ on 5m and 15m; keep a 3m SPY lane exploratory only. Include realistic costs, one position at a time, fixed risk, and both 2R and time-based exits.
3. Evaluate by date-blocked walk-forward splits and require cross-market improvement after multiple-testing correction. Any apparent winner remains shadow-only until forward evidence accumulates.
4. Add OPRA/contract-feasibility joining separately; underlying backtest returns do not establish option profitability.

The social claims about turning small accounts into large sums are examples/marketing, not independently verified expectancy. They are useful for generating hypotheses, not for promotion.
