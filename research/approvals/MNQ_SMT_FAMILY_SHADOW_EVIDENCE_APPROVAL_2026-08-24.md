# MNQ SMT Family — Shadow Evidence Approval

- Approval date: 2026-08-24
- Owner: Kenny
- Scope: delayed Databento historical regrade of the four frozen `mnq-smt-cisd-family` shadow candidates
- Status: approved for shadow evidence collection and later promotion review

Kenny's directive to finish the Databento gap authorizes removal of the
`kenny_signoff_required` blocker **only** when a post-preregistration signal is
independently reproduced from Databento `GLBX.MDP3` OHLCV and resolved from a
complete, integrity-checked reconstructed MNQ MBO book.

This approval does not authorize live orders, automatic execution, broker
writes, relaxing a frozen strategy rule, counting proxy fills, or bypassing
the 100-outcome / 30-date / regime-coverage / BH-FDR promotion gates.

- `execution_enabled=false`
- `can_submit_orders=false`
- `orders_submitted=0`
