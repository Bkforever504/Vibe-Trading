# X SPY Research API Setup

Date: 2026-07-24 CT

## Configured

- X Developer account accepted and active.
- Existing X app reused.
- App-only Bearer Token regenerated and stored only in ignored
  `agent/.env` as `X_BEARER_TOKEN`.
- No token or account credential was committed.
- Auto-recharge remains disabled.
- No card, billing information, or credits were added.

## Connector

```text
scripts\x_spy_research_intake.py
scripts\run_x_spy_research_intake.ps1
agent\tests\test_x_spy_research_intake.py
```

The connector:

- uses X API v2 recent search;
- searches SPY options, gamma, VWAP, volume, and order-flow discussion;
- requests 10 posts per manual run by default;
- allows one request per day and 20 per month by default;
- records every attempted request, including diagnostic/no-write requests;
- labels every post as unverified, outcome-test-required, and
  execution-ineligible;
- has no broker or strategy-gate connection.

## Current Blocker

The live authentication request reached X successfully but returned:

```text
HTTP 402: credits depleted
```

The Developer Console showed a zero-dollar balance. X API access is currently
pay-per-use, so no post data can be retrieved until Kenny explicitly purchases
credits. Do not enable auto-recharge or purchase credits without a new,
explicit approval.

## Verification

```text
17 X/public-social tests passed
Bearer Token configured in ignored local environment
No execution path enabled
```

After credits are explicitly approved and available:

```powershell
Set-Location C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading
.\scripts\run_x_spy_research_intake.ps1
```

Do not schedule this collector until several manual responses have been
reviewed for relevance and X usage costs have been confirmed in the console.
