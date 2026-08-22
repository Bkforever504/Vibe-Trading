# Codex Handoff: TopstepX Chrome Account Setup — 2026-08-10

## Objective

Use the browser (Playwright/Chrome) to walk Kenny through getting
the three TopstepX credential values needed to activate the MES
market recorder. Then write those values into `agent/.env`.

Do not submit any orders, buy any subscriptions, or enable execution.

---

## Context

The repo has a complete read-only MES microstructure data pipeline built
by a prior Codex session (see `CODEX_HANDOFF_TOPSTEP_CURRENT_REGIME_2026-08-10.md`).
It is blocked on missing credentials. The pipeline does nothing until
the env vars exist — it exits cleanly with a "missing credentials" message.

Files already built and waiting:
- `strategies/topstepx_market_recorder.py` — read-only SignalR recorder
- `scripts/run_topstepx_practice_probe.ps1` — probe script
- `scripts/run_topstepx_market_recorder.ps1` — data collection runner
- `research/topstepx_microstructure_features.py` — feature builder

---

## Required Credentials

Three env vars are needed in `agent/.env`:

```
TOPSTEPX_USERNAME=          # TopstepX login email or username
TOPSTEPX_API_KEY=           # API key from the TopstepX developer portal
TOPSTEPX_PRACTICE_ACCOUNT_ID=  # Numeric account ID of the Practice account
TOPSTEPX_LOCAL_DEVICE=PERSONAL_DEVICE_CONFIRMED
```

---

## Browser Steps

### Step 1 — Check for existing TopstepX account

Navigate to `https://topstepx.com` and check if Kenny already has an account.
Ask Kenny: "Do you have a TopstepX login? If yes, what email did you use?"

If no profile exists, guide Kenny through registration at topstepx.com. A
Topstep profile itself is free, but a Practice account is available only while
an eligible Trading Combine subscription is active. Do not purchase one during
this workflow.

### Step 2 — Log in

Navigate to the TopstepX platform and log in with Kenny's credentials.
Do NOT print or log the password at any point.

### Step 3 — Find or create the Practice account

After login, navigate to account management. Look for:
- "Practice Account" or "Sim Account" or "Paper Trading"
- If none exists, create one — it's free
- Note the numeric account ID (usually shown in account list or URL)

The practice account ID is a number like `123456` or similar. If the account
list is empty and no active Trading Combine exists, stop and report the paid
subscription prerequisite.

### Step 4 — Get the API key

Look for an API or Developer section. Common paths:
- Account Settings → API
- Developer Portal (may be a separate subdomain like `api.topstepx.com`)
- Profile → Integrations or API Keys

TopstepX API access is a separate paid ProjectX subscription. Do not subscribe
or generate a key without explicit purchase authorization from Kenny.
If TopstepX has a self-serve API key portal and API access is already active,
generate a new key.
If API keys require a support request, note that and stop — Kenny will need
to email support before this can proceed.

### Step 5 — Write credentials to agent/.env

Once you have all three values, open `agent/.env` (already exists in the repo)
and append the following block. Do NOT display the actual key values in chat —
write them directly to the file:

```python
# ============================================================================
# TopstepX MES Market Recorder (read-only data collection)
# See: strategies/topstepx_market_recorder.py
# Setup guide: CODEx_CLAUDE_COLLAB/CODEX_HANDOFF_TOPSTEP_CURRENT_REGIME_2026-08-10.md
# ============================================================================
TOPSTEPX_USERNAME=<value>
TOPSTEPX_API_KEY=<value>
TOPSTEPX_PRACTICE_ACCOUNT_ID=<value>
TOPSTEPX_LOCAL_DEVICE=PERSONAL_DEVICE_CONFIRMED
# Leave blank until a strategy passes forward evidence and Combine risk gates:
# TOPSTEPX_PRACTICE_EXECUTION=
```

### Step 6 — Verify

After writing the file, run in PowerShell from the repo root:
```powershell
python scripts/run_topstepx_practice_probe.ps1
```

The probe should connect, confirm the Practice account, and exit cleanly.
If it errors with an auth failure, the key or username is wrong — fix it.
If it errors with "execution disabled", that is correct — do not override it.

---

## Hard Constraints

- Do NOT print `TOPSTEPX_API_KEY` value anywhere in chat output.
- Do NOT enable execution: leave `TOPSTEPX_PRACTICE_EXECUTION` blank.
- Do NOT buy a Combine ($50K or otherwise).
- Do NOT place any practice or live orders.
- Do NOT install a Task Scheduler task for the recorder yet.
  (Scheduler comes after the manual smoke test passes cleanly.)
- If API keys require a TopstepX support ticket or waitlist, stop and report
  the exact blocker. Do not substitute synthetic data or fake credentials.

---

## Success Criteria

Session is complete when:
1. `agent/.env` contains the four `TOPSTEPX_*` vars (key value never shown in chat)
2. `scripts/run_topstepx_practice_probe.ps1` exits with no auth errors
3. A status artifact `data/topstepx_market_recorder_status.json` shows
   `"authenticated": true` and `"execution_enabled": false`

If TopstepX API is behind a waitlist or requires a paid Combine to access,
report that blocker in the handoff so Kenny can decide next steps.

---

## Verified Blocker - 2026-08-10

Chrome inspection confirmed that Kenny already has a Topstep profile and is
logged into `dashboard.topstep.com`. The Trading Accounts page shows zero
accounts. The sign-up link logs him in because the profile already exists; it
does not create a Practice account.

Current official requirements:

- Practice Account: free only with an active Trading Combine subscription.
- Lowest listed Trading Combine standard path: $49/month for 50K.
- TopstepX API access: separate ProjectX subscription, listed as $29/month or
  $14.50/month with Topstep's recurring discount code.
- No API sandbox is available.

No purchase was authorized or made. No API key was generated, no environment
credential was written, and execution remains disabled. This setup cannot
continue until Kenny explicitly decides whether to accept both paid
prerequisites.

---

## What Comes Next (after this session)

The next Codex session will:
1. Run the market recorder during RTH (9:30 AM – 4:00 PM ET)
2. Accumulate 20 complete trading sessions of MES data
3. Preregister one microstructure hypothesis before analyzing outcomes
4. Test it chronologically with doubled costs and exact Topstep Combine rules

No strategy research until 20 sessions of live data are collected.
