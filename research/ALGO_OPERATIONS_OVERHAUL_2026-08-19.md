# Algorithm Operations Overhaul

Date frozen: 2026-08-19

## Objective

Convert useful practices from Jan - Algo Trader and stronger systematic-trading
sources into measurable controls for the existing paper/shadow system. This
work does not copy private strategies, claim guaranteed profitability, or grant
research code execution authority.

## Jan review

Primary material reviewed:

- [Jan - Algo Trader](https://www.youtube.com/@algojan)
- [Your Forex Trading Bot Will Fail. Here Is Why - And How To Fix It](https://www.youtube.com/watch?v=2vxN63ADloc)
- Jan's monthly win/loss reviews and public track-record discussions.
- [Jan's Myfxbook profile](https://www.myfxbook.com/members/jalgo)

Adopted:

1. Backtests must include fees, spread, slippage, delays, partial/rejected fills,
   and gap risk where the source data supports them.
2. A strategy is regime-dependent and must have explicit suspend and recovery
   rules.
3. Risk cannot increase after a loss. Martingale, grid averaging, and averaging
   down are prohibited.
4. Diversification is measured from synchronized outcomes and joint losses, not
   from strategy names or asset count.
5. Losing periods and execution misses remain in the evidence packet.
6. Forward evidence and verified broker results outrank screenshots and demo
   equity curves.

Not adopted:

- High leverage, because return comparisons without normalized risk are
  misleading and incompatible with the current safety boundaries.
- A tiny live sample as a substitute for untouched out-of-sample testing.
- A basket of similar breakout systems as proof of diversification.
- Any strategy rule disclosed without exact timestamps, costs, rejected trades,
  and losing periods.

## Similar systematic sources reviewed

| Source | Useful practice | Local implementation |
|---|---|---|
| [Kevin Davey / KJ Trading Systems](https://www.youtube.com/@KJTradingSystems) | Walk-forward testing, Monte Carlo stress, parameter stability, and rejecting fragile systems | Existing adversarial audit retained; lifecycle now requires repeated passing reviews |
| [QuantConnect](https://www.youtube.com/@QuantConnect) and [reality modeling](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/slippage/key-concepts) | Brokerage, fee, fill, slippage, latency, and market-impact assumptions must match deployment | Forward fill evidence is compared with the modeled entry gap |
| [Robot Wealth](https://www.youtube.com/@RobotWealthTV) and [Edge Alchemy](https://robotwealth.com/edge-alchemy/) | Start with an economic mechanism, combine small edges, and measure portfolio diversification | Pairwise return correlation, loss-event correlation, and joint-loss lift added |
| [Darwinex](https://www.youtube.com/@Darwinex) and [investable attributes](https://help.darwinex.com/what-are-investable-attributes) | Compare track records at normalized risk and weight statistical experience | Fixed/reduced risk invariant, evidence counts, and no automatic risk escalation |
| [Sersan Sistemas interview](https://music.youtube.com/podcast/hYzRW3LsLzw) | Portfolio oversight must react to abnormal regimes without rewriting history | Preregistered suspend/recovery state machine and immutable report fingerprint |

## Frozen controls

### Dependence

- Minimum pairwise overlap: 20 synchronized dates.
- High dependence when return correlation is at least 0.65, binary loss-event
  correlation is at least 0.35, or joint-loss lift is at least 1.50 with at
  least five joint losses.
- A high-dependence pair is treated as one risk sleeve. The report recommends a
  combined 35% research-weight cap, but cannot alter production allocation.

### Execution reality

- Minimum: 10 broker-confirmed forward fills with entry evidence.
- High drift: average adverse fill versus signal ask exceeds the larger of 3%
  or twice the modeled gap, or p95 adverse fill exceeds 5%.
- Watch drift: average exceeds the larger of 1.5% or 1.25 times the modeled gap,
  or p95 exceeds 3%.
- High drift suspends new promotion reviews; it does not modify orders.

### Suspend and recovery

- At least 30 resolved observations.
- Positive 90% moving-block bootstrap lower bound.
- Passing frozen sign-flip placebo test.
- Stable recent edge-decay status.
- Two consecutive passing reviews are required before `review_ready`.
- Promotion and reactivation always require human approval.

### Reproducibility

Every run hashes the protocol, this document, the pipeline, the options twin,
and the primary options bot. The monthly evidence packet records the combined
SHA-256 fingerprint. A changed fingerprint triggers comparison; it is not code
signing and does not prove correctness.

## Authority boundary

The pipeline and monthly packet always emit:

- `execution_enabled: false`
- `can_submit_orders: false`
- `orders_submitted: 0`
- `promotion_authority: blocked`

No order client is imported. No strategy is promoted, reactivated, resized, or
changed by this report.
