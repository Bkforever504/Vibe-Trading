# Swing Cash Sleeve Preregistration

Date: 2026-08-13
Status: frozen before cash-sleeve outcomes are computed
Mode: research only; no execution authority

## Hypothesis

The preregistered breadth overlay reduced equity exposure when fewer than 60%
of the twelve-symbol universe traded above its completed 200-session average.
Its residual allocation was incorrectly modeled as zero-return cash. Allocate
that residual to BIL, a liquid 1-3 month Treasury-bill ETF, without increasing
gross exposure above 100%.

## Frozen Variants

1. `equal_weight_baseline`: unchanged 100% equity baseline.
2. `breadth_zero_cash`: unchanged breadth overlay with residual earning 0%.
3. `breadth_bil_cash`: same equity exposure and signals as `breadth_zero_cash`;
   residual allocation earns BIL's next-open to twentieth-session-close return.

Only one new hypothesis, `breadth_bil_cash`, is tested. BIL bars must be known
point in time. Ordinary round-trip cost is 10 bps, charged pro rata to both the
equity and Treasury sleeves. Stress cost is 30 bps. No leverage is permitted.
Only fully resolved 20-session holding windows are scored.

## Chronology And Gates

- Development: 2015-2022.
- Selection diagnostic: 2023-2025.
- Variant-sealed but non-pristine diagnostic: 2026 through 2026-07-20.

The cash sleeve passes only if it increases ending equity and lowers maximum
drawdown relative to `equal_weight_baseline` in both development and selection,
keeps 30-bps expectancy positive in every window, keeps top-1%-removed
expectancy positive in every window, and has a positive development bootstrap
lower bound. Passing permits shadow observation only.
