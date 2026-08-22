# MES OFI Scalping Preregistration

Date: 2026-08-13
Mode: research only; no execution authority
Status: frozen before outcomes are computed

## Data And Signal

Use the existing Databento-derived `mes_bbo_ofi_30s_2024_2026.parquet` cache.
For each contract/session, standardize the completed 30-second bucket's OFI
against the prior 60 completed buckets. A signal requires absolute z-score at
least 2.5, at least 20 quote-seconds in both signal and exit buckets, and a
one-tick or tighter spread at signal and exit.

The two frozen hypotheses are:

1. `ofi_momentum_scalp`: trade in the direction of OFI.
2. `ofi_reversal_scalp`: trade opposite OFI.

Enter at the completed signal bucket's executable ask for a long or bid for a
short. Exit at the next consecutive bucket's executable bid or ask. Require a
five-minute cooldown and allow no more than three trades per session.

## Costs And Validation

- MES multiplier: $5 per point.
- Base round-trip commission: $2.48; spread crossing is embedded in fills.
- Stress: $4.96 commission plus one adverse tick per side ($2.50 total).
- Chronological split by sessions: 60% development, 20% selection, 20% final.
- No parameter sweep or post-result threshold changes.

A candidate needs at least 100 trades, positive selection and final expectancy
under base and stress costs, positive top-1%-removed expectancy in selection
and final, profit factor above one in selection and final, and positive PnL in
both halves of the final split. Passing permits shadow observation only.
