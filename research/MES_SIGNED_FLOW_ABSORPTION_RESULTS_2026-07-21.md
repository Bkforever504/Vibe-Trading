# MES Signed-Flow Absorption Discovery Result

Date: 2026-07-21
Status: rejected as infeasible; no strategy outcomes opened

## Billing Safety

- Databento portal balance before and after download: $0.00.
- Credits before download: $52.82.
- Download estimate and credit usage: $29.33.
- Credits after download: $23.49.
- No card charge was authorized or incurred.

## Phase A

The credit-only `GLBX.MDP3` trade-print slice was joined to the existing BBO
cache after removing the 2025-11-28 degraded session and the 2025-12-17 roll
session.

- 15,885,210 RTH prints;
- 61 complete sessions;
- 22,080 one-minute windows;
- 99.9968% of prints matched to a prior quote within two seconds;
- 99.9999% of matched volume received an aggressor sign.

All preregistered data-quality gates passed. The feed is suitable for measuring
signed flow and contemporaneous price response.

## Phase B

Before opening outcomes, one rule was frozen at the outcome-blind marginal
distribution landmarks: at least 5,000 contracts, absolute imbalance at least
0.40, and absolute one-minute mid displacement at most 0.50 points.

That conjunction produced zero candidate windows. No entries, exits, future
prices, or P&L were opened. Per the preregistration, the thresholds will not be
loosened or searched on this consumed period.

## Verdict

The specific one-minute extreme-flow/stalled-price rule is rejected as
infeasible. This does not revive the failed quote-imbalance strategy and does
not authorize MES execution. `VibeTradingNinjaTraderMESSim` must remain
disabled.

The defensible continuation is forward-only mechanism discovery: log signed
flow, volume-conditioned price response, and quote/trade latency on later
sessions without orders. A new strategy rule may be frozen only from those
later outcome-blind observations, then evaluated on still-later data.
