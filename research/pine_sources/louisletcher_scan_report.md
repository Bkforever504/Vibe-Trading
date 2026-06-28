# Pine Source Scan Report

Root: `research\pine_sources\louisletcher-quant-pine`

| Metric | Count |
|---|---:|
| Pine files | 4 |
| Indicators/studies | 1 |
| Strategies | 3 |
| Clean files | 1 |
| Warning files | 3 |
| Critical repaint files | 0 |

## Translation Queue

Clean files below have no current scanner warnings. They are not approved strategies; they are candidates for manual translation and backtesting.

| File | Name | Type | Category | Version | License | Tags |
|---|---|---|---|---:|---|---|
| `src/pinescripts/indicators/free/conners-relative-strength-index.pine` | Connors Relative Strength Index | indicator | src | 5 | unknown | RSI |

## Strategy Review Queue

Non-critical strategy files below still need realistic cost settings, repaint review, Python translation, and full OOS/WF/PBO testing before they can become candidates.

| File | Name | Category | Version | License | Warnings | Tags |
|---|---|---|---:|---|---|---|
| `src/pinescripts/strategies/free/02_stocks/bullish_engulfing.pine` | Stocks - Bullish Engulfing | src | 6 | unknown | no_commission, no_slippage, pine_v6 | RSI |
| `src/pinescripts/strategies/free/02_stocks/inside-days.pine` | Stocks - Inside Day Strategy | src | 6 | unknown | no_commission, no_slippage, pine_v6 | RSI |
| `src/pinescripts/strategies/free/02_stocks/stan-weinstein.pine` | Stocks - Stan Weinstein Stage 2 Breakout Strategy | src | 6 | unknown | request_security, no_commission, no_slippage, pine_v6 | SMA |

## Flagged Files

| File | Critical | Warnings |
|---|---|---|
| `src/pinescripts/strategies/free/02_stocks/bullish_engulfing.pine` | - | no_commission, no_slippage, pine_v6 |
| `src/pinescripts/strategies/free/02_stocks/inside-days.pine` | - | no_commission, no_slippage, pine_v6 |
| `src/pinescripts/strategies/free/02_stocks/stan-weinstein.pine` | - | request_security, no_commission, no_slippage, pine_v6 |
