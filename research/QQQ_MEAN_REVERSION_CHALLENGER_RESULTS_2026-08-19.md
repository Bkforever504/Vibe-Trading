# QQQ Mean-Reversion Challenger Results

Date: 2026-08-19

## Verdict

No variant passed the experiment-wide promotion gate. All remain read-only
shadow hypotheses. The test did identify two useful drawdown challengers and
several context hypotheses for forward measurement.

The sealed selection period beginning 2023-01-27 and sealed final period
beginning 2024-10-21 were not opened.

## Baselines and exit challengers

All dollar figures use $10,000 notional and include 4 bps round-trip cost.

| Variant | Trades | Expectancy | Win rate | PF | Max DD | Avg hold | Worst MAE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Double 7 baseline | 68 | $71.54 | 73.5% | 1.81 | $1,035 | 8.52 | -15.35% |
| Double 7 / SMA5 exit | 86 | $52.66 | 69.8% | 2.00 | $750 | 4.63 | -10.91% |
| RSI2 baseline | 106 | $61.36 | 71.7% | 1.80 | $1,692 | 8.20 | -25.44% |
| RSI2 / prior-high exit | 136 | $51.90 | 77.9% | 2.14 | $1,182 | 4.32 | -11.51% |

The faster exits traded some expectancy for materially lower drawdown and tail
excursion:

- Double 7 SMA5 reduced max drawdown by 27.5%, worst MAE by 28.9%, and average
  holding time by 45.7%.
- RSI2 prior-high reduced max drawdown by 30.1%, worst MAE by 54.8%, and average
  holding time by 47.3%.

Neither corrected p-value passed `0.05 / 921`. These are shadow challengers, not
proven improvements.

## Other tested changes

- A rising SMA(200) modestly increased Double 7 expectancy from $71.54 to
  $74.84, but did not reduce drawdown or pass multiple-test correction.
- A one-ATR next-open gap guard did not improve either family.
- Volatility scaling reduced RSI2 drawdown from $1,692 to $1,362 but also
  reduced expectancy from $61.36 to $52.04.
- Requiring both Double 7 and RSI2 weakened expectancy and bootstrap evidence.
- Restricting Double 7 to turn-of-month sessions weakened the result and left
  too few observations.

## Exploratory context findings

These were observed after the frozen variants and therefore have no gate
authority:

- Double 7 entries with a 2.5%-5% drawdown from the 20-day high had stronger
  development expectancy than shallow pullbacks.
- RSI2 performance was weakest in the highest realized-volatility tercile.
- Both baselines performed worse near turn of month in this sample.
- Weekday differences were large but too small and too exposed to selection
  bias to use as filters.

The logger records these fields so forward data can falsify them. A future test
must preregister exact thresholds before using any sealed or forward outcomes.

## Operational status

- New logger: `scripts/qqq_mean_reversion_shadow.py`
- New report: `scripts/qqq_mean_reversion_shadow_report.py`
- Log: `data/qqq_mean_reversion_shadow_log.jsonl`
- Existing scheduled task: `RSI2ShadowLogger`, daily at 3:20 PM Central
- Data route confirmed: Alpaca market data
- Execution enabled: false
- Can submit orders: false

The first new snapshot used the 2026-08-18 completed bar. Both Double 7 variants
armed a next-open virtual entry. RSI2 state inherited from before the forward
protocol is labeled observe-only and cannot count as a resolved forward trade.
No order was submitted.

## Research references

- Nagel, *Evaporating Liquidity*: https://doi.org/10.1093/rfs/hhs066
- de Groot, Huij, and Zhou, *Another Look at Trading Costs and Short-Term
  Reversal Profits*: https://doi.org/10.1016/j.jbankfin.2011.07.015
- Moreira and Muir, *Volatility-Managed Portfolios*:
  https://doi.org/10.3386/w22208
