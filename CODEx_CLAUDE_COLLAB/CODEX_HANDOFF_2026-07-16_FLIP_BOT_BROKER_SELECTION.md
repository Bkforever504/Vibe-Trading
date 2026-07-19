# Codex Handoff - Flip Bot Broker Selection

Date: 2026-07-16
Owner: Codex + Claude Code shared context
Repo: C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading

## Why This Exists

Kenny is preparing for a future funded Flip Bot launch with an initial account around USD 1,000 after the ORB/retest paper evidence checks out. This note preserves the broker research and current execution-venue decision so we do not forget it or accidentally steer the bot toward the wrong cost structure.

This is not approval to trade live. It is the broker-selection baseline for the next adapter work.

## Current Decision

Use Alpaca paper for development and validation, but do not assume Alpaca is the best first funded venue for a USD 1,000 0DTE options account.

Recommended funded venue order as of 2026-07-16:

1. Webull OpenAPI, if API approval is granted and real-time options data access is usable.
2. Tradier Pro, if Webull API approval/data is blocked.
3. Tradier Lite, if the user wants USD 0 monthly fixed cost and accepts USD 0.35 per option contract.
4. Alpaca, excellent current integration but likely too expensive for small-account live 0DTE if real-time OPRA requires the USD 99/month plan.
5. tastytrade, strong API/sandbox but higher per-contract cost for small quick scalps.

Robinhood is not ready for bot execution in this repo. The official Agentic MCP was connected successfully, but it advertised zero usable tools to Codex, including `get_accounts`. Treat this as a Robinhood-side provisioning/compatibility blocker until read-only account discovery works. Robinhood Legend is manual UI only and does not fix MCP/API tool access.

## Important Cost Correction

Kenny remembered correctly that Alpaca has a "100 dollars" issue.

Clarification: Alpaca does not require a USD 100 account minimum for trading, and options commissions are not the issue. The concern is market data. Alpaca's Algo Trader Plus market data plan is USD 99/month and is the path to real-time OPRA/full SIP coverage. For a USD 1,000 account, that is about 9.9% of starting capital every month before any trade P&L.

For 0DTE options execution, stale or indicative bid/ask is not acceptable for live sizing, entry, exits, or path telemetry.

## Broker Notes

### Alpaca

Pros:
- Already integrated in the bot stack.
- Live and paper options support.
- Official API/MCP support exists.
- Cleanest current engineering path.

Cons:
- USD 99/month market data plan is too heavy for a USD 1,000 first live account if required for real-time options data.
- Keep using Alpaca paper development unless/until a better first-funded venue adapter is ready.

### Webull

Pros:
- Official OpenAPI supports stocks/options/futures/crypto.
- Options API supports single-leg and multi-leg orders, plus limit, stop, stop-limit, take-profit/stop-loss, OCO/OTOCO patterns.
- API eligibility starts with an active brokerage account and minimum net account value of USD 100, subject to Webull review.
- Cash account structure can avoid PDT problems by using settled funds; options settlement is T+1.

Cons:
- API access is reviewed and can take 1-2 business days.
- App Key/App Secret validity is short, default 1 day and max 7 days, so credential rotation must be handled operationally.
- Webull Cloud MCP currently appears read/query oriented and does not expose order placement; live execution likely requires direct OpenAPI integration.

### Tradier

Pros:
- Official live and sandbox APIs.
- Real-time streaming available.
- Tradier Pro is USD 10/month and has commission-free equity/ETF options, excluding regulatory/exchange fees.
- Tradier Lite has no monthly fee and USD 0.35/contract, which may be cheaper if trade frequency stays low.

Cons:
- Requires building a new adapter.
- Sandbox fills and delayed data must not be confused with live quality.

### tastytrade

Pros:
- Official Open API, sandbox, real-time options data, and multi-leg support.
- Strong options-native platform.

Cons:
- USD 1/contract to open and USD 0 to close, capped at USD 10 per leg. This can matter for small-account 0DTE scalps.
- Sandbox resets every 24 hours.

### TradeStation / IBKR

These are valid professional venues but are lower priority for the first funded Flip Bot launch because they add setup complexity and/or higher friction. Revisit after Webull/Tradier are evaluated.

## Next Engineering Work

1. Keep Flip Bot paper execution and shadow telemetry unchanged.
2. Build a broker adapter abstraction before any funded broker switch:
   - quote snapshot
   - option chain lookup
   - order preview/dry run
   - single-leg buy-to-open
   - close position
   - account buying power
   - positions/orders reconciliation
3. Implement Webull read-only adapter first if API access is granted.
4. Implement Tradier sandbox adapter in parallel or as fallback.
5. Require an execution-gate audit before any new adapter can submit orders.
6. Never wire Robinhood live until read-only discovery works and a formal order-placement path is verified.

## Live Readiness Boundary

No live execution simply because a broker is chosen.

Before live:
- ORB/retest strategy must have forward paper evidence.
- Loss/win reason taxonomy must be correct.
- Path telemetry must capture best/worst P&L and exit quality.
- Broker quotes must be real-time enough for 0DTE decisions.
- Manual human approval required.
- Starting size should be small enough that a full stop does not threaten the account.

## Official Source Links Used

- Alpaca market data pricing: https://alpaca.markets/data
- Alpaca options trading: https://docs.alpaca.markets/us/docs/options-trading
- Alpaca MCP: https://docs.alpaca.markets/us/docs/alpaca-mcp-server
- Alpaca options fees: https://alpaca.markets/support/what-are-the-commission-fees-per-option-contract
- Webull API access: https://www.webull.com/help/faq/10512-Does-Webull-offer-API
- Webull Cloud MCP: https://developer.webull.com/apis/docs/AI-friendly-Resources/mcp/
- Webull options API: https://developer.webull.com/apis/docs/trade-api/options/
- Webull trading API overview: https://developer.webull.com/apis/docs/trade-api/overview/
- Webull day trading rules: https://www.webull.com/help/faq/10954-Day-Trading-Rules/
- Tradier endpoints: https://docs.tradier.com/docs/endpoints
- Tradier pricing: https://production.tradier.com/individuals/tradier-pro
- tastytrade API: https://tastytrade.com/api/
- tastytrade pricing: https://tastytrade.com/pricing/
- TradeStation API: https://developer.tradestation.com/trading-api/
- IBKR API: https://www.interactivebrokers.com/campus/ibkr-api-page/twsapi-doc/

