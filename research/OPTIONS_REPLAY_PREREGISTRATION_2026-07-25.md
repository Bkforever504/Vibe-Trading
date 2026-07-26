# Preregistration: SPY 12:00 Option Replay on Expired-Contract Data

Date frozen: 2026-07-25, before the first replay run.
Purpose: test whether the 12:00 SPY signal's underlying-bps lead survives
real option premiums, spreads, and convexity. This is an execution-truth
experiment, not a new signal search.

## Frozen Inputs

- Signal set: rows in `data/green_day_htf_ltf_results_per_checkpoint.json`
  (already-registered trial `green-day-htf-ltf-2026-07-25`), checkpoint
  12:00 only, variants `ltf_only` (control) and `daily_aligned` (candidate),
  session dates >= 2024-03-01 (start of free Alpaca option history).
  Unique (date, direction) pairs are replayed once and tagged with variant
  membership. No new signals may be generated.
- Data: Alpaca expired-contract 1-minute option bars (free feed confirmed by
  `scripts/alpaca_options_history_probe.py`). No purchases.

## Frozen Contract Selection

- Direction bull -> CALL, bear -> PUT.
- Strike: `round(underlying_entry_price)` (SPY $1 strikes near the money).
- Expiry buckets per signal:
  - `0dte`: same session date;
  - `1dte`: next calendar trading day (weekend-skipping; holiday gaps count
    as unavailable);
  - `3_7dte`: the smallest DTE in [3,7] calendar days whose contract has bar
    data.
- A bucket with no bar data is recorded `unavailable`, never substituted.

## Frozen Execution Model

- Entry: option bar open at exactly 12:00 ET, buy at
  `price * (1 + half_spread)`; missing 12:00 bar = skip (counted).
- Exit: close of the last option bar in [12:45, 12:59] ET, sell at
  `price * (1 - half_spread)`; no bar in that window = skip (counted).
- `half_spread = rel_spread / 2` with an absolute floor of $0.02 per side.
- `rel_spread` calibration: 75th percentile of observed (ask-bid)/mid from
  the forward NBBO capture log (`option-quote-samples.jsonl`, SPY contracts
  with valid bid/ask). If fewer than 10 valid samples exist, use the frozen
  fallback `rel_spread = 0.04`. The calibration source and value are
  recorded in the output.
- Commissions: $0.65 per contract per side plus $0.01 fees, on a 100
  multiplier ($1.32 per contract round trip).
- Timezone: bars are filtered by converted ET times, never fixed UTC
  offsets, so DST cannot shift the window.

## Outcome Measures and Interpretation

- Per bucket x variant: count, mean option return %, win rate, profit
  factor, top-1%-removed mean, skip/unavailable counts.
- Underlying-bps results from the parent trial are reported alongside for
  contrast but are not option results.
- 2024-03+ dates were consumed by the parent trial; this replay is
  diagnostic execution evidence, not out-of-sample proof.
- No promotion, sizing, or production change may result directly from this
  run. The only permitted follow-up remains a frozen forward shadow lane,
  human-approved.

## Execution

```powershell
uv run --no-project --with pandas --with numpy --with requests --with python-dotenv `
  python research/options_replay_lab.py
```

Output: `data/options_replay_results.json`
Promotion authority: human (Kenny) only.
