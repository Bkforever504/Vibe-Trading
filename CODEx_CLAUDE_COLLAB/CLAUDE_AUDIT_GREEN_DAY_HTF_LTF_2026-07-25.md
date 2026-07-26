# Claude Adversarial Audit: Green-Day HTF/LTF Lab

Date: 2026-07-25
Subject: `research/green_day_htf_ltf_lab.py` and
`data/green_day_htf_ltf_results.json`
Stance per handoff: attack the result; stop after audit and proposed patches.
Audit tool: `research/green_day_audit_checks.py` (read-only, committed).

## What Passed the Attack

1. **No HTF look-ahead.** `asof_states` uses strictly-before filtering.
   Empirically proven on live caches: a Friday session (2026-07-17) sources
   its weekly label from the week ending 2026-07-10, never its own unfinished
   week; a mid-month session (2026-07-10) sources its monthly label from
   2026-06-30. Partial resample bins carry future period-end labels and are
   therefore excluded automatically by the strict inequality.
2. **No intraday look-ahead.** Signals are computed on bars strictly before
   the checkpoint; entry uses the checkpoint bar's open (next-bar-open
   discipline). Bar labels are open-time stamped, so the last history bar is
   fully completed at signal time.
3. **Timezone integrity.** The minute parquet is tz-aware
   America/New_York (2022-01-03 to 2026-07-17); no naive-UTC mislabeling.
   Extended-hours bars (e.g. 16:13) exist but are excluded by
   `between_time("09:30","15:59")`.
4. **Same-bar stop/target ambiguity resolved conservatively.** Stop is
   checked before target inside each bar, so double-touch bars count as
   losses.
5. **Cache freshness.** SPY daily cache runs 2015-01-02 through 2026-07-20,
   covering the replay window.
6. **Honest options labeling.** Outcome labels are explicitly
   `outcome_label_only_no_fill_pnl_inference`, consistent with the P0
   finding that 12 of 13 closed options records lack fill-derived P&L.
7. **Robustness features are correctly oriented.** Top-1%-removed expectancy
   removes the best trades; bootstrap is block-based and seeded.

## Findings (severity order)

### F1. Complete-session filter creates a volatility-skewed sample (material)

Only 467/1,137 sessions (41%) pass the all-minutes-present-through-13:44 IEX
rule, and the included sample is systematically different:

| Metric | Included (467) | Excluded (670) |
|---|---:|---:|
| Mean session range | 1.342% | 1.093% |
| Mean abs close-to-open move | 0.726% | 0.569% |
| Median session volume | 1.50M | 0.996M |

IEX minute completeness is a proxy for high activity, so every expectancy in
the replay is conditioned on "high-volatility day" without that condition
being part of the strategy. The sign of the induced bias is unknown; the
sample is simply not representative. All replay expectancies (including the
12:00 daily-aligned lead) must be read as conditional estimates.

### F2. Confidence-interval claims exceed what the code produces (minor but misleading)

`_block_bootstrap` returns no CI below 20 observations. Cells like the 12:00
selection window (n=3) therefore have `[None, None]`; any narrative "negative
CI lower bound" for those cells cannot come from this code and should be
restated as "sample too small for a CI".

### F3. Missing `right` defaults to bearish in the flip reconstruction (latent)

`direction = "bull" if right == "CALL" else "bear"` silently classifies a
missing/invalid right as a PUT. Current 12 records all carry `right`, so no
damage yet, but this is exactly the class of silent default the taxonomy
repair exists to eliminate. Should route through
`scripts/lifecycle_normalizer.normalize_flip_trade`, which quarantines it.

### F4. Options reconstruction bypasses the canonical adapter (latent)

`recovered_mleg` is treated as "neutral" instead of quarantined-unknown, and
structure direction logic is re-implemented locally instead of using
`lifecycle_normalizer` (which the repo already tests). Two direction
implementations will eventually disagree.

### F5. Lab/production signal parity is unverified (evidence gap)

`ltf_signal` claims to mirror the production 9-point VWAP/EMA recipe, but no
test feeds the same synthetic session to both this function and the
production scanner scoring. Agreement was only spot-checked against 12 actual
trades (via `reconstructed_ltf_agrees`). If the mirror drifts, every replay
row describes a strategy the bot does not trade.

### F6. Half-days are structurally excluded (disclosure)

The 13:44 completeness rule can never pass on early-close days, so holiday
half-days are absent from the sample. Acceptable, but should be listed in
`data_warnings`.

## Proposed Patch Set (for review — none applied)

- **P1 (F1):** Preregister one replication with per-checkpoint completeness
  (all minutes from 09:30 through checkpoint+65m only). This roughly doubles
  eligible sessions per checkpoint without forward-filling, and lets the
  included/excluded volatility gap be reported per window. No parameter may
  change; this is the same frozen rule on a wider, still-honest sample.
- **P2 (F3/F4):** Replace local direction/eligibility logic in the lab's
  reconstruction sections with `lifecycle_normalizer` views; quarantined
  records report `unknown` instead of defaulting.
- **P3 (F5):** Add a parity test: one synthetic session evaluated by both
  `green_day_htf_ltf_lab.ltf_signal` and the production scanner's scoring
  path must emit the same 9/9 verdict and direction.
- **P4 (F2):** In `metrics`, emit `ci_status: "insufficient_n"` when the
  bootstrap returns None so downstream text cannot invent a CI.
- **P5 (F6):** Append the half-day exclusion to `data_warnings`.
- **P6:** Register this experiment (prereg SHA, code commit, partitions,
  variant count = 3 checkpoints x 6 variants x 3 outcome measures) in the
  immutable trial registry before any 12:00 forward shadow lane starts, so
  multiplicity is counted. The registry itself is still the open P0-C task.

## Verdict on the Handoff's Conclusions

- 10:30 rejection: stands (and is strengthened; F1 bias means even the
  2022-23 +1.90 bps is conditional).
- 12:00 daily-aligned "promise": overstated. n=3 selection, no valid CI,
  volatility-conditioned sample. Forward shadow lane is the only honest next
  step, exactly as the handoff proposes.
- Monthly rotation as strongest HTF evidence: consistent with the frozen
  momentum lane's primacy; survivorship caveat remains real (cache universe
  is today's 29 liquid names).
- No retuning was performed in this audit; consumed periods stay consumed.
