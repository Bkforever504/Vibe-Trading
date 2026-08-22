# MES MBO Liquidity-Response Preregistration

Date: 2026-08-12
Status: frozen after Phase A mechanics, before acquiring discovery sessions
Authority: research only; no execution or routing authority

## Single Hypothesis

When aggressive flow hits one side but the resting book replenishes in that
same direction, liquidity providers are absorbing the pressure and the next
30-second executable markout follows the replenishing side.

- Bullish absorption: passive bid fill imbalance `>= 0.43`, cancel/add pressure
  `>= 0.067`, and top-of-book depth imbalance `>= 0.48` in the same completed
  five-second window.
- Bearish absorption: all three values are at or below the mirrored negative
  thresholds.
- No neutral or mixed-sign window is a signal.

These thresholds are fixed from Phase A distribution landmarks, not outcomes.
No alternative thresholds may be evaluated on the discovery sample.

## Executable Measurement

- Signal is known only after its five-second window closes.
- Enter at the next valid reconstructed BBO: ask for bullish, bid for bearish.
- Exit after six additional five-second windows: bid for bullish, ask for
  bearish.
- MES value: $5 per point.
- Commissions and fees: $1.24 per side, $2.48 round trip.
- Stress case: one additional tick adverse on entry and exit plus doubled fees.
- Overlapping signals are suppressed until the current 30-second markout ends.

## Discovery Sample

- Candidate sessions priced before acquisition: 2026-07-16 ($1.2438),
  2026-07-17 ($1.6211), and 2026-07-20 ($1.3796) UTC.
- Budget amendment made before acquisition and without viewing outcomes: acquire
  2026-07-16 and 2026-07-20 only. Their combined estimate is $2.6234. The
  three-session estimate of $4.2445 exceeded the frozen $4.00 cap.
- Phase A session 2026-07-15 is excluded from all outcome calculations.
- Full UTC sessions are required to reconstruct the opening snapshot.

## Discovery Gates

- At least 30 non-overlapping signals.
- Positive base expectancy and profit factor at least 1.20.
- Positive stressed expectancy and profit factor at least 1.05.
- Both bullish and bearish directions represented by at least 10 signals.
- No single session contributes more than 50% of total positive P&L.

Passing discovery does not establish an edge. It permits one untouched
validation request with unchanged rules. Failure retires this exact hypothesis;
the thresholds, horizon, and conjunction may not be retuned on these sessions.

## Budget Gate

- Estimate every session before download.
- Combined discovery download cap: $4.00.
- Reconstructed credits before discovery: $22.26.
- Minimum reserve after discovery: $15.00.
- No card charge is authorized.
