# Pine Source Scan Report

Root: `research\pine_sources\alorse-pinescript-strategies`

| Metric | Count |
|---|---:|
| Pine files | 70 |
| Indicators/studies | 23 |
| Strategies | 47 |
| Clean files | 14 |
| Warning files | 56 |
| Critical repaint files | 2 |

## Translation Queue

Clean files below have no current scanner warnings. They are not approved strategies; they are candidates for manual translation and backtesting.

| File | Name | Type | Category | Version | License | Tags |
|---|---|---|---|---:|---|---|
| `indicators/3 MA + Cross.pine` | 3 EMA/SMA + Cross [Alorse] | study | indicators | 4 | unknown | EMA, SMA |
| `indicators/5 EMA SMA + Cross.pine` | 5 EMA SMA WMA + Cross [Alorse] | indicator | indicators | 5 | mpl-2.0 | EMA, SMA |
| `indicators/BB + 3EMA.pine` | Simple Bollinger Bands + 3 EMA/SMA [Alorse] | study | indicators | 4 | unknown | EMA, SMA |
| `indicators/BB Winner.pine` | Bollinger Bands Winner IND [Alorse] | study | indicators | 4 | unknown | EMA, SMA, RSI, ATR |
| `indicators/Candle Percent Volatility [Alorse].pine` | Percent & Volatility [Alorse] | indicator | indicators | 5 | mpl-2.0 | - |
| `indicators/DMI + RSI Cross.pine` | Directional Movement Index [Alorse] | study | indicators | 4 | unknown | RSI |
| `indicators/DMI.pine` | DMI Trade Zone [Alorse] | indicator | indicators | 5 | unknown | - |
| `indicators/KDJ.pine` | KDJ + MACD Cross [Alorse] | study | indicators | 4 | unknown | EMA, SMA, MACD |
| `indicators/MACD.pine` | MACD | study | indicators | 4 | unknown | EMA, SMA, MACD |
| `indicators/PivotHighLow.pine` | PivotHighLow | study | indicators | 4 | unknown | EMA, MACD |
| `indicators/Range Filter [Alorse].pine` | Range Filter | indicator | indicators | 5 | unknown | EMA |
| `indicators/SuperTrend FromScrash.pine` | Supertrend From Scratch [Alorse] | indicator | indicators | 5 | unknown | ATR |
| `indicators/TTM Squeeze.pine` | TTM Squeeze [Alorse] | indicator | indicators | 5 | unknown | EMA, SMA |
| `indicators/Williams Vix Fix + Inverse.pine` | Williams Vix Fix + Inverse [Alorse] | study | indicators | 4 | unknown | SMA |

## Strategy Review Queue

Non-critical strategy files below still need realistic cost settings, repaint review, Python translation, and full OOS/WF/PBO testing before they can become candidates.

| File | Name | Category | Version | License | Warnings | Tags |
|---|---|---|---:|---|---|---|
| `strategies/MTF RSI.pine` | MTF RSI | strategies | 5 | mpl-2.0 | no_slippage | EMA, SMA, RSI |
| `strategies/MTF+MACD.pine` | MACD + Divergences [Alorse] | strategies | 4 | unknown | no_slippage | EMA, SMA, MACD, ATR |
| `strategies/MacdNew.pine` | MACD + Divergences [Alorse] | strategies | 4 | unknown | no_slippage | EMA, SMA, MACD |
| `strategies/grid/GridBotDir [Alorse].pine` | Grid Bot Simulator [Alorse] | strategies | 5 | mpl-2.0 | no_slippage | - |
| `strategies/mean-reversion/BB + Aroon.pine` | Bollinger bands + Aroon [Alorse] | strategies | 5 | mpl-2.0 | no_slippage | SMA |
| `strategies/mean-reversion/BB Winner LITE.pine` | Bollinger Bands Winner LITE [Alorse] | strategies | 4 | unknown | no_slippage | SMA |
| `strategies/mean-reversion/BB Winner PRO.pine` | Bollinger Bands Winner PRO [Alorse] | strategies | 5 | unknown | no_slippage | EMA, SMA, RSI, ATR |
| `strategies/mean-reversion/Bollinger Breakout [kodify].pine` | Bollinger Breakout [kodify] | strategies | 4 | unknown | no_slippage | SMA |
| `strategies/mean-reversion/Exceeded candle.pine` | Exceeded candle [Alorse] | strategies | 4 | unknown | no_slippage | SMA |
| `strategies/momentum/DMI Winner.pine` | Directional Movement Index Winner [Alorse] | strategies | 5 | unknown | no_slippage | EMA, SMA |
| `strategies/momentum/MACD + BB + RSI.pine` | MACD + BB + RSI [Alorse] | strategies | 5 | unknown | no_slippage | EMA, SMA, RSI, MACD |
| `strategies/momentum/MACD + DMI.pine` | MACD + DMI | strategies | 4 | mpl-2.0 | no_slippage | MACD, ATR |
| `strategies/momentum/MACD Long Strategy [Bunghole].pine` | MACD Long Strategy [Alorse] | strategies | 5 | mpl-2.0 | no_slippage | RSI, MACD |
| `strategies/momentum/QQE signals.pine` | QQE signals [Alorse] | strategies | 4 | mpl-2.0 | no_slippage | EMA, RSI |
| `strategies/momentum/RSI + EMA.pine` | RSI + EMA [Alorse] | strategies | 5 | mpl-2.0 | no_slippage | EMA, SMA, RSI |
| `strategies/momentum/Stoch RSI Crossover Strat + EMA - YT-Trade Pro.pine` | Stoch RSI Crossover Strat + EMA - YT:Trade Pro | strategies | 4 | unknown | no_slippage | EMA, SMA, RSI, ATR |
| `strategies/momentum/StochRSI + Supertrend Strategy.pine` | StochRSI + Supertrend Strategy [Alorse] | strategies | 4 | unknown | no_slippage | EMA, SMA, RSI, ATR |
| `strategies/momentum/TTM Squeeze.pine` | TTM Squeeze [Alorse] | strategies | 5 | unknown | no_slippage | EMA, SMA, RSI |
| `strategies/momentum/Williams Vix Fix.pine` | Williams Vix Fix Strategy [Alorse] | strategies | 4 | unknown | no_slippage | SMA |
| `strategies/other/Full Candle.pine` | Full Candle [Alorse] | strategies | 5 | mpl-2.0 | no_slippage | EMA |
| `strategies/other/Improvising [Alorse].pine` | Improvising [Alorse] | strategies | 5 | unknown | no_slippage | EMA, RSI, MACD |
| `strategies/other/Omar MMR [Alorse].pine` | Omar MMR [Alorse] | strategies | 5 | mpl-2.0 | no_slippage | EMA, RSI, MACD |
| `strategies/other/Pin Bar Magic v1.pine` | Pin Bar Magic v1 | strategies | 4 | unknown | no_slippage | EMA, SMA, ATR |
| `strategies/other/StratBase.pine` | Strat base [Alorse] | strategies | 5 | unknown | no_slippage | EMA |
| `strategies/other/TTM Squeeze EMA Strategy [Alorse].pine` | Improvising [Alorse] | strategies | 5 | unknown | no_slippage | EMA, SMA |
| `strategies/trend/Double Supertrend.pine` | Double Supertrend [Alorse] | strategies | 5 | mpl-2.0 | no_slippage | ATR |
| `strategies/trend/EMA Moving away Strategy [Alorse].pine` | EMA Moving away Strategy [Alorse] | strategies | 5 | unknown | no_slippage | EMA |
| `strategies/trend/MA Cross + DMI.pine` | MA Cross + DMI [Alorse] | strategies | 4 | unknown | no_slippage | EMA, SMA |
| `strategies/trend/Supertrend + EMA rebound [Alorse].pine` | Supertrend + EMA rebound [Alorse] | strategies | 5 | mpl-2.0 | no_slippage | EMA, ATR |
| `strategies/trend/Supertrend + RSI.pine` | Supertrend + RSI Strategy [Alose] | strategies | 5 | mpl-2.0 | no_slippage | RSI, ATR |
| `strategies/trend/Supertrend.pine` | Supertrend [Alorse] | strategies | 4 | unknown | no_slippage | ATR |
| `strategies/trend/Tendency EMA + RSI.pine` | Trend EMA + RSI [Alorse] | strategies | 5 | mpl-2.0 | no_slippage | EMA, RSI |
| `multi/Alert BB + RSI.pine` | Alert BB + RSI [Alorse] | multi | 4 | unknown | legacy_security, no_slippage | SMA, RSI, MACD |
| `strategies/MTF BB.pine` | MTF Bollindger Bands Strategy [Alorse] | strategies | 4 | mpl-2.0 | legacy_security, no_slippage | EMA, SMA, ATR |
| `strategies/mean-reversion/BB Divergence.pine` | Bollinger Bands Divergence [Alorse] | strategies | 4 | unknown | no_commission, no_slippage | SMA |
| `strategies/mean-reversion/MEMA + BB + RSI [Alorse].pine` | MEMA + BB + RSI [Alorse] | strategies | 5 | unknown | request_security, no_slippage | EMA, SMA, RSI |
| `strategies/mean-reversion/Multi BB.pine` | Multi Bollinger Bands [Alorse] | strategies | 4 | mpl-2.0 | legacy_security, no_slippage | SMA |
| `strategies/momentum/Double RSI.pine` | Double RSI [Alorse] | strategies | 5 | mpl-2.0 | request_security, no_slippage | RSI |
| `strategies/momentum/MACD+RSI.pine` | MACD + RSI Strategy [Alorse] | strategies | 4 | mpl-2.0 | no_commission, no_slippage | EMA, SMA, RSI, MACD |
| `strategies/momentum/RSI + 1200.pine` | RSI + 1200 Strategy [Alose] | strategies | 5 | mpl-2.0 | request_security, no_slippage | EMA, RSI |
| `strategies/other/Flawless Victory.pine` | Flawless Victory | strategies | 4 | mpl-2.0 | no_commission, no_slippage | SMA, RSI |
| `strategies/other/Omar Edited WF.pine` | Omar Edited WF | strategies | 5 | mpl-2.0 | request_security, no_slippage | EMA, RSI |
| `strategies/other/Password protected.pine` | Password for my scripts [Alorse] | strategies | 4 | unknown | no_commission, no_slippage | EMA, SMA |
| `strategies/other/Strategy Tester [Lupown].pine` | Strategy Tester | strategies | 5 | mpl-2.0 | no_slippage, pivot_repaint | SMA, ATR |
| `strategies/trend/HA UnivLong&Short Futures.pine` | HA UnivLong&Short Futures | strategies | 5 | unknown | request_security, no_commission, no_slippage | SMA |

## Flagged Files

| File | Critical | Warnings |
|---|---|---|
| `indicators/MACD Divergence.pine` | - | pivot_repaint |
| `indicators/MTF+MACD.pine` | - | request_security, pivot_repaint |
| `indicators/RSI Divergence.pine` | - | pivot_repaint |
| `indicators/TTM Squeeze + MACD Line.pine` | - | pivot_repaint |
| `multi/Alert BB + RSI.pine` | - | legacy_security, no_slippage |
| `multi/Multi MACD + BB + RSI.pine` | - | request_security |
| `multi/Multi MTF + MACD.pine` | - | request_security, pivot_repaint |
| `multi/Multi RSI Divergence.pine` | - | request_security, pivot_repaint |
| `multi/Multi Supertrend.pine` | - | request_security |
| `multi/RSI Multi Alerts.pine` | - | request_security |
| `strategies/grid/GridBotDir [Alorse].pine` | - | no_slippage |
| `strategies/MacdNew.pine` | - | no_slippage |
| `strategies/mean-reversion/BB + Aroon.pine` | - | no_slippage |
| `strategies/mean-reversion/BB Divergence.pine` | - | no_commission, no_slippage |
| `strategies/mean-reversion/BB Winner LITE.pine` | - | no_slippage |
| `strategies/mean-reversion/BB Winner PRO.pine` | - | no_slippage |
| `strategies/mean-reversion/Bollinger Breakout [kodify].pine` | - | no_slippage |
| `strategies/mean-reversion/Exceeded candle.pine` | - | no_slippage |
| `strategies/mean-reversion/MEMA + BB + RSI [Alorse].pine` | - | request_security, no_slippage |
| `strategies/mean-reversion/Multi BB.pine` | - | legacy_security, no_slippage |
| `strategies/momentum/DMI Winner.pine` | - | no_slippage |
| `strategies/momentum/Double RSI.pine` | - | request_security, no_slippage |
| `strategies/momentum/MACD + BB + RSI.pine` | - | no_slippage |
| `strategies/momentum/MACD + DMI.pine` | - | no_slippage |
| `strategies/momentum/MACD Long Strategy [Bunghole].pine` | - | no_slippage |
| `strategies/momentum/MACD+RSI.pine` | - | no_commission, no_slippage |
| `strategies/momentum/QQE signals.pine` | - | no_slippage |
| `strategies/momentum/RSI + 1200.pine` | - | request_security, no_slippage |
| `strategies/momentum/RSI + EMA.pine` | - | no_slippage |
| `strategies/momentum/Stoch RSI Crossover Strat + EMA - YT-Trade Pro.pine` | - | no_slippage |
| `strategies/momentum/StochRSI + Supertrend Strategy.pine` | - | no_slippage |
| `strategies/momentum/TTM Squeeze.pine` | - | no_slippage |
| `strategies/momentum/Williams Vix Fix.pine` | - | no_slippage |
| `strategies/MTF BB.pine` | - | legacy_security, no_slippage |
| `strategies/MTF RSI.pine` | - | no_slippage |
| `strategies/MTF+MACD.pine` | - | no_slippage |
| `strategies/other/Flawless Victory.pine` | - | no_commission, no_slippage |
| `strategies/other/Full Candle.pine` | - | no_slippage |
| `strategies/other/Improvising [Alorse].pine` | - | no_slippage |
| `strategies/other/Javo v1 [Repaint].pine` | lookahead_on | request_security, no_slippage |
| `strategies/other/Omar Edited WF.pine` | - | request_security, no_slippage |
| `strategies/other/Omar MMR [Alorse].pine` | - | no_slippage |
| `strategies/other/Password protected.pine` | - | no_commission, no_slippage |
| `strategies/other/Pin Bar Magic v1.pine` | - | no_slippage |
| `strategies/other/StratBase.pine` | - | no_slippage |
| `strategies/other/Strategy Tester [Lupown].pine` | - | no_slippage, pivot_repaint |
| `strategies/other/TTM Squeeze EMA Strategy [Alorse].pine` | - | no_slippage |
| `strategies/trend/Double Supertrend.pine` | - | no_slippage |
| `strategies/trend/EMA Moving away Strategy [Alorse].pine` | - | no_slippage |
| `strategies/trend/HA UnivLong&Short Futures.pine` | - | request_security, no_commission, no_slippage |
| `strategies/trend/Heikin Ashi Strategy V2 [FAKE].pine` | lookahead_on | legacy_security, no_commission, no_slippage |
| `strategies/trend/MA Cross + DMI.pine` | - | no_slippage |
| `strategies/trend/Supertrend + EMA rebound [Alorse].pine` | - | no_slippage |
| `strategies/trend/Supertrend + RSI.pine` | - | no_slippage |
| `strategies/trend/Supertrend.pine` | - | no_slippage |
| `strategies/trend/Tendency EMA + RSI.pine` | - | no_slippage |
