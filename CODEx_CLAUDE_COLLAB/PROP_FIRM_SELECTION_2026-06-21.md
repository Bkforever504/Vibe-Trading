# Prop Firm Selection: Automation-First Futures Bot

Date: 2026-06-21

Goal: choose the best first prop firm for Kenny's automated/semi-automated futures bot.

## Recommendation

Start with Topstep.

Topstep is the best first fit for this project because:

- TopstepX API Access officially supports building and running automated trading strategies.
- Topstep has public docs for pricing, subscriptions, Trading Combine parameters, TopstepX, and API access.
- Futures are the right arena for Topstep, MNQ/MES, and opening-range/VWAP testing.
- Our current rule gate already has a Topstep profile.
- The 50K Trading Combine is inexpensive enough to test once the local replay backtester shows promise.

Important: this is not a claim that Topstep is the easiest place to get paid. It is the best first fit for a disciplined automation build.

## Compared Firms

### Topstep

Verdict: Primary target.

Why:

- Official TopstepX API page says API access lets traders/developers build and run automated strategies.
- The same API page says trading must originate from a personal device and VPS/VPN/remote servers are prohibited.
- Trading Combine is simulated and has no fixed time limit.
- Pricing page currently lists 50K at $49/month Standard Path and $95/month No Activation Fee Path.

Risks:

- Must obey Topstep's current rules exactly.
- API automation cannot be run on VPS/cloud under current public guidance.
- We need local machine reliability if using automation.

Sources:

- `https://help.topstep.com/en/articles/11187768-topstepx-api-access`
- `https://help.topstep.com/en/articles/8284197-trading-combine-parameters`
- `https://help.topstep.com/en/articles/14289835-topstep-pricing-and-payment-questions`
- `https://help.topstep.com/en/articles/8284121-trading-combine-subscriptions`

### Take Profit Trader

Verdict: Not first for automation.

Why:

- Official PRO Account Rules say no trading bots/algos and all trades must be manually executed.
- It may be attractive for discretionary/manual trading, but it conflicts with our preferred automated system.

Sources:

- `https://takeprofittraderhelp.zendesk.com/hc/en-us/articles/15171769361053-PRO-Account-Rules`
- `https://takeprofittrader.com/`

### Tradeify

Verdict: Secondary research candidate, not first.

Why:

- Tradeify has attractive funded structures and public rules/content.
- Funded agreement includes audit/review rights over trading activities and styles.
- Public plan pages mention consistency and payout constraints.
- Automation policy needs direct official confirmation before any bot work.

Sources:

- `https://tradeify.co/funded-trader-agreement`
- `https://help.tradeify.co/en/articles/10468318-guidelines-for-traders`
- `https://tradeify.co/post/tradeify-3-0-here-and-everything-just-changed`

## Decision

Use Topstep as the first prop-firm target.

Account path:

1. Local replay backtester.
2. Local paper/shadow trading.
3. Topstep Practice Account if active Combine exists.
4. 50K Trading Combine after strategy-profit confidence improves.
5. No funded/live automation until all gates pass.

## Confidence Scores

Topstep fit for automation-first build: 8.5/10

Reason:

- Strong official API fit.
- Clear public docs.
- Reasonable 50K entry cost.
- Rule gate already exists.
- Main weakness is local-only execution and strategy edge not proven yet.

Take Profit Trader fit for automation-first build: 3/10

Reason:

- Official PRO rules prohibit bots/algos.

Tradeify fit for automation-first build: 5/10

Reason:

- Potentially viable, but automation policy and exact account rules need direct verification.

## What Claude Code Should Do Next

Proceed with Topstep-first replay backtester.

Do not build multi-firm execution yet.

Do not build Take Profit Trader automation.

Do not add Tradeify automation until official current automation permission is verified and converted into a JSON rule profile.

