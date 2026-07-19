# Flip Bot Broker Selection Research Snapshot

Date: 2026-07-16
Canonical handoff: C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\CODEx_CLAUDE_COLLAB\CODEX_HANDOFF_2026-07-16_FLIP_BOT_BROKER_SELECTION.md

## Bottom Line

For a future USD 1,000 funded Flip Bot account, keep Alpaca as the paper/development venue but prioritize Webull OpenAPI or Tradier for first funded execution.

Alpaca is technically strongest in the current repo, but the USD 99/month market data plan is too expensive as a fixed drag on a small 0DTE options account if real-time OPRA/full SIP is required.

## Current Ranking

1. Webull OpenAPI - first choice if approved and data access is adequate.
2. Tradier Pro - likely best paid fallback at USD 10/month.
3. Tradier Lite - best zero-monthly fallback, with USD 0.35/contract.
4. Alpaca - keep for paper/dev; revisit live if market-data cost is solved.
5. tastytrade - strong but less ideal for small quick scalps due open-contract fees.

## Do Not Forget

- Robinhood Agentic MCP connected but showed zero usable tools to Codex. Do not fund or integrate until read-only discovery works.
- Robinhood Legend login does not help automated execution.
- Webull Cloud MCP appears read/query oriented; order placement likely needs direct OpenAPI.
- Webull API keys may need frequent renewal, so credential operations matter.
- Tradier sandbox is useful, but delayed/simulated fills are not live edge proof.

## Implementation Reminder

Do not hard-code a broker switch into `flip_bot.py`. Build a small broker adapter layer with read-only discovery first, then paper/sandbox, then order submission only after the execution audit passes.

