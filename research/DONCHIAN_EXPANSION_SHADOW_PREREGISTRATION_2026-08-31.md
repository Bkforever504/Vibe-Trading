# Donchian expansion shadow challenger — preregistration

## Scope

This is an isolated U.S.-equity, completed-5-minute-RTH **candidate coverage**
challenger. It is not an entry strategy and cannot submit orders, rank A+
candidates, change alerts, assign sizing, or make a profitability claim.

## Frozen observation definition

For the newest completed five-minute regular-session bar of an eligible symbol:

1. Compare its close with the high/low of the **preceding 20 completed bars**;
   the signal bar is excluded from both Donchian levels and the volume baseline.
2. Require volume to be at least `1.25 ×` the mean volume of those preceding
   20 completed bars.
3. Require a bullish close in the upper 60% of its range, or a bearish close in
   the lower 40%.
4. Require its true range (including gaps) to be strictly greater than
   `1.20 ×` the mean true range of the preceding 14 completed bars.

The report records standard breakout status separately from the strict range
expansion status. Only a strict hit is passed back to the main radar as a
same-day *coverage nomination*.

## Data and integrity rules

- RTH bars only; extended-hours bars cannot satisfy the setup.
- Missing, incomplete, zero-range, or insufficient-history inputs produce an
  explicit unavailable record, never a proxy signal.
- The initial universe is the liquid core plus the current radar candidate
  set. It is a bounded discovery lane, not a claim of whole-market coverage.
- No Yahoo data, imported third-party ML artifact, historical performance
  claim, fill assumption, or external strategy score is used.

## Promotion requirements

Before any change in authority, define one entry deadline/order convention,
invalidation, exit/time rule, costs and spread filters, per-trade/portfolio
risk limits, and a point-in-time eligible universe. Then compare against the
current A+ baseline in date-partitioned cost-aware walk-forward research and a
separate forward shadow sample. Promotion requires improvement after costs and
no degradation of the existing catalyst, liquidity, and market-regime gates.

## Frozen forward-shadow policy

The observation now has an explicitly separate underlying-price outcome lane:

1. Enter at the **open of the next completed five-minute bar**, provided it
   arrives within 30 minutes of the signal.
2. Use the signal-bar low as the long stop or signal-bar high as the short
   stop. Invalid geometry is rejected rather than resized.
3. Take `2R`, otherwise exit after 60 minutes. If a single OHLC bar spans both
   stop and target, resolve it as a stop first.
4. Apply 5 basis points of slippage per side to the underlying. This is a
   stress assumption, not a claim of executable NBBO fills.

The append-only ledger preserves the original signal timestamp and cannot be
rewritten by later scanner output.

## Provenance

- [Source-code intake](ELICHERLA01_BREAKOUTSCANNER_INTAKE_2026-08-31.md)
- [Original repository](https://github.com/Elicherla01/breakoutscanner)
