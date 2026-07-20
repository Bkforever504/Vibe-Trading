# Preregistration Part 2: MES Quote-Flow Edges, Distribution-Calibrated

Date: 2026-07-19
Status: frozen before any outcome analysis at these thresholds
Owner: Claude (research only, no execution)

## Why Part 2 Exists

Part 1 thresholds (0.35/0.50 rolling, 0.25 opening) were set before seeing
the data and turned out to be unreachable during RTH: the MES top-of-book
is deep and balanced, and the 300-second mean absolute imbalance tops out
at 0.40 with p99 = 0.136. Part 1 configs are recorded as zero-signal
(untestable as frozen). Part 2 recalibrates thresholds using ONLY
signal-frequency distribution data - no trade outcomes were computed or
inspected at any new threshold before this file was frozen.

## Changes from Part 1 (everything else identical)

- H1 thresholds: +/-0.10 (RTH p97) and +/-0.14 (RTH p99).
- H3 opening threshold: 0.10; minimum opening-window coverage relaxed to
  60 seconds (the 200-second gate produced zero qualifying sessions).
- Results file: `data/mes_orderflow_results_part2.json`.

Same execution realism (buy ask/sell bid + $1.24 commission per side,
stress adds 2x commission and 1 tick per side), same splits, same gates,
same consumed-window caveat, same limits: four configs, fail = rejected,
no third calibration round on this sample.
