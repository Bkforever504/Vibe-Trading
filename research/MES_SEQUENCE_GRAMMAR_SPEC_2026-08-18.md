# MES Sequence Grammar Tournament

Date: 2026-08-18  
Status: frozen before simulation  
Authority: development-only research; no order or promotion authority

## Fixed Grammar

The tournament evaluates all 288 combinations of:

- Liquidity reference: completed 15-minute opening range, completed 30-minute opening range, previous completed session, or causal session VWAP.
- Event: close-through breakout or wick-through/close-back sweep-reclaim.
- Confirmation: none, volume at least 1.2 times the previous six-bar mean, or directional body at least 0.6 times the previous six-bar ATR proxy.
- Entry: signal-bar close, next completed directional bar, or first level retest/rejection within six bars.
- Exit: 1R, 1.5R, 2R, or 3R.

Common rules: 10:00-11:30 ET signals, one MES contract, one trade per session, structural stop, 4-60 tick risk, 60-minute maximum hold, stop-first same-bar handling, and $4.98 baseline round-trip friction with doubled-friction stress.

## Governance

Only the first 70% of sessions may be used. It is divided into three chronological regimes. The next 15% and last 15% are not opened by this program. Existing documented attempts are 515; this registry raises the effective attempt count to 803 and uses one-sided Bonferroni alpha `0.05 / 803`.

A development survivor requires at least 20 trades, positive expectancy, and PF above 1.0 in every development regime; positive doubled-friction aggregate expectancy; and an aggregate p-value below the corrected alpha. A survivor is only a forward-shadow hypothesis because the broader historical dataset has been reused by prior research.
