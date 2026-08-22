# HUT Social Setup Audit - 2026-08-20

## Claim reviewed

The supplied social screenshots described a HUT bullish setup using:

- daily hammer entry near 83.00;
- 4-hour 3-1 reversal entry near 82.77;
- bullish call trigger above 84.34;
- one-ATR upside reference near 91.66;
- a claimed 150% option return.

The screenshots do not provide the option contract, timestamped entry fill,
executable bid/ask at entry and exit, stop, size, or complete alert history.
The return claim is therefore not independently verified.

## System finding

The original intraday radar did not discover HUT. It was absent from the top
market-activity lists and from the repository's static universe. This was a
coverage failure before any strategy gate ran.

After the discovery repair, the 2026-08-20 refresh reported:

- discovered: 476 symbols;
- evaluated with 5-minute data: 100 symbols;
- HUT pipeline stage: evaluated;
- direction: bullish;
- setup: opening-range breakout;
- price at refresh: 86.92;
- session high: 88.60;
- above opening range: true;
- above VWAP proxy: true;
- structure component: 92/100;
- overall setup score: 52.6, grade C;
- factor-consensus score: 47.6, grade D;
- average 20-day dollar volume: about $23.8 million;
- current-session dollar volume: about $14.5 million;
- IEX quote spread: 3.185%, failed;
- catalyst in the available news feed: none.

The radar now identifies the move but does not issue an order. The displayed
IEX spread is not a substitute for option NBBO. A contract recommendation
requires a separate live option-chain check, executable spread/open-interest
gates, a timestamped trigger, and an invalidation.

## Changes made

- Always nominate the standing liquid universe instead of only labeling names
  already found by market screeners.
- Add liquid thematic names, including HUT and crypto-miner peers.
- Add same-day nominees from broad market news, the deep-universe scan, daily
  stock screener, premarket radar, and social research.
- Increase the completed-bar evaluation budget from 50 to 100 symbols.
- Balance that budget across move magnitude, activity, and standing liquid
  names so noisy microcaps cannot consume every slot.
- Add a per-symbol coverage trace with the exact stage where analysis stopped.

## Verdict

The chart sequence is a reasonable research candidate, not a verified edge.
The important repair is that HUT can no longer disappear before evaluation.
Promotion requires forward outcomes and executable option quotes, not social
percentage screenshots.
