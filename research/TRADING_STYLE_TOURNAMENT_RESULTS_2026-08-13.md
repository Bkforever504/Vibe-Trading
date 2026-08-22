# Trading Style Tournament Results

Date: 2026-08-13
Mode: research only; no execution authority

## Verdict

The repository's strongest current research style is monthly cross-sectional
swing momentum in liquid technology equities and ETFs. No style is eligible
for production or paper promotion yet.

| Style | After-cost result | Sample | Verdict |
|---|---:|---:|---|
| Monthly swing momentum | +297.73 bps/period; +277.73 at 30 bps | 30 periods | Research leader |
| MES opening-gap fade | +$28.48/trade at 2x cost | 8 trades | Too few outcomes |
| Best public MES intraday replication | Negative after base costs | 591 trades | Rejected |
| MES OFI momentum scalp | -$9.54/trade stressed final | 1,920 total | Rejected |
| MES OFI reversal scalp | -$7.88/trade stressed final | 1,920 total | Rejected |
| 0DTE first-mark filter | +14.87% midpoint post-fee | 562, 19 dates | Executable gate failed |

The 100-family MES discovery tournament had zero survivors across 515 effective
attempts. Five public intraday strategy replications also had zero historical
survivors. More intraday variants are not justified until a materially better
data feature or execution advantage exists.

## Swing Toolbox Priorities

1. Preserve the monthly momentum core and collect new completed periods.
2. Add point-in-time universe membership to remove survivorship bias.
3. Cap every stock at 35%; place residual capital in BIL rather than forcing
   concentration.
4. Add slow-moving, point-in-time signals with economic grounding: earnings
   estimate revisions/PEAD, quality/profitability, 52-week-high proximity, and
   sector-relative strength. Test each as a separate preregistered challenger.
5. Use breadth and volatility as sizing controls, not hard trade-level stops.
6. Cluster correlated holdings so SPY, QQQ, XLK, SMH, and mega-cap technology
   do not masquerade as independent risk.
7. Measure next-open, VWAP, and patient-limit implementation shortfall before
   changing the alpha signal.
8. Keep scalping disabled unless a future order-book feature produces positive
   expectancy after spread, fees, slippage, latency, and top-tail removal in
   both selection and final periods.

## Research Context

Recent practitioner discussion remains dominated by screenshots and subjective
claims. The useful recurring point is that short-horizon systems are unusually
sensitive to slippage and spread, while swing systems tolerate retail execution
better. Primary research is consistent: individual day traders pay a measurable
cost of immediacy, transaction costs can erase short-term reversal, and momentum
costs differ materially by liquidity. These findings support emphasizing liquid
swing momentum rather than increasing trade frequency.

No orders were submitted and no execution configuration changed.
