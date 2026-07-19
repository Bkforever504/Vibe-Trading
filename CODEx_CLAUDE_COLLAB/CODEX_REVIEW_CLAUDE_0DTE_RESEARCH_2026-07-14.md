# Codex Review - Claude 0DTE Research - 2026-07-14

## Accepted and implemented

- Confirmed Flip uses a five-bar, five-minute opening range.
- Added point-in-time ORB breakout-candle range divided by prior ATR(5) as
  forward telemetry. It is recorded in the entry feature snapshot and does
  not block, approve, or resize a trade.
- Hardened the existing GEX scanner. It now requires same-day expiration,
  real open-interest coverage of at least 60%, and explicit provenance.
- Removed displayed ask-size substitution and all-expiration fallback.
- Market Force now rejects legacy or provenance-incomplete GEX rows.

## Already present

- GEX scanner, scheduled task, log, market-force integration, and tests.
- Five-minute ORB.
- VIX term-structure context and RV/IV regime context.
- Entry cutoff, hard close, MFE/MAE path telemetry, fixed target/stop, and
  tiered profit-protection ratchet.
- Time-bucket shadow report.
- Expected-move normalization added by Codex immediately before this review.

## Not promoted to live behavior

- GEX is not a proven directional oracle. The scanner is a call-minus-put
  gamma/open-interest proxy and does not observe dealer inventory.
- No 12:00-13:30 hard gate. The cited 13:30 bucket has only nine completed
  shadow lifecycles and is not enough to establish a robust exclusion window.
- No VIX 15/20 hard thresholds. The research did not establish stable OOS
  expectancy for those cutoffs.
- No ATR >= 0.8 entry gate. The ratio is now captured so the claim can be
  tested without introducing selection bias.
- No 80%-of-max-profit rule for long calls or puts because their theoretical
  maximum is not bounded. Existing spread and long-option exits remain intact.

## Forward tests

1. Compare ORB outcomes by candle/ATR bins: `<0.8`, `0.8-1.2`, `>1.2`.
2. Compare time windows by symbol and regime with realistic bid/ask costs.
3. Compare provenance-qualified GEX confirm, conflict, and unavailable groups.
4. Cross each result with expected-move consumption and RV/IV regime.
5. Record every attempted variant in the edge trial ledger before promotion.
