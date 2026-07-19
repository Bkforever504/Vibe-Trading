# Decisions

## 2026-06-21: Separate Prop Arena

Decision:

The Topstep prop bot is separate from the Alpaca options bot.

Reason:

Alpaca options and Topstep futures are different markets, risk models, and rule environments. Keeping them separate prevents accidental cross-contamination.

## 2026-06-21: Paper/Shadow First

Decision:

No live or funded-account execution until replay/paper evidence exists.

Reason:

The rule gate can be high-confidence before the strategy is profitable. Strategy-profit confidence requires data.

## 2026-06-21: First Strategy Candidate

Decision:

Start with MNQ/MES opening-range breakout with VWAP confirmation.

Reason:

It is simple, testable, futures-native, and compatible with prop-firm constraints.

## 2026-06-21: Confidence Score Split

Decision:

Track separate confidence scores:

- Compliance/rule-gate confidence
- Strategy-profit confidence

Reason:

A high-quality compliance gate does not prove a trading edge.

