# First-Mark Momentum Gate Replay Specification - 2026-08-12

## Evidence Status

This is a frozen post-discovery replay specification, not an independent
preregistration. The same shadow corpus was already inspected by
`research/flip_filter_lab.py`, which identified the first-mark split. Results
from that corpus are exploratory and consumed-history evidence.

The first independent evidence begins with later shadow dates collected after
this specification and the implementation code hash are frozen. Nothing in
this replay has live or paper execution authority.

## Input and Measurement

- Input: `data/flip_shadow_candidates_log.jsonl`.
- Unit: one resolved lifecycle with a shadow entry and shadow exit.
- Confirmation signal: midpoint-based `return_pct_at_mark` on the first
  recorded post-entry observation.
- Executable replay: entry at recorded ask and exit at recorded bid.
- Fallback prices are allowed only when explicitly labeled in coverage fields.
- Cost proxy: subtract 1.5 percentage points per completed trade; doubled-cost
  stress subtracts 3.0 percentage points.

The first recorded mark is usually near five minutes but is not guaranteed to
be exactly five minutes because scheduler phase varies. The report must expose
the elapsed-time distribution and must not call this a fixed five-minute bar.

## Frozen Policies

All gates require the first observation to arrive at least zero and less than
ten minutes after the entry timestamp. Missing, negative, or later elapsed time
is ineligible and falls back to the logged exit.

1. `baseline_no_gate`: use the logged lifecycle exit.
2. `gate_mark1_any_negative`: exit at the eligible first observation when
   signal return is less than or equal to zero.
3. `gate_mark1_below_minus5`: exit at the eligible first observation when
   signal return is strictly below -5%.
4. `gate_mark1_below_minus10`: exit at the eligible first observation when
   signal return is strictly below -10%.

No additional threshold may be added after replaying this corpus. A later
threshold requires a new dated specification and untouched dates.

## Required Reporting

- sample and unique-date counts;
- changed-exit count;
- post-fee and doubled-cost expectancy;
- win rate, profit factor, average win/loss, and maximum additive drawdown;
- top-5%-winner-removed expectancy;
- chronological last-20%-of-dates diagnostic;
- entry-ask and exit-bid coverage;
- first-observation elapsed-time distribution;
- first-mark-green review-gate status from `flip_filter_lab`;
- an executable-policy review gate requiring at least 30 samples, at least 20
  dates, and positive post-fee, doubled-cost, and top-5%-removed expectancy.

## Authority

The lab is read only. It cannot submit orders, mutate configuration, select a
winner automatically, or promote a policy. Reaching 20 dates is insufficient
by itself: both the midpoint diagnostic and executable gate must pass before a
human paper-review request is emitted. A review request does not authorize
paper or live trading.
