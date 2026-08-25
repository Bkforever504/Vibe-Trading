# Shadow Scanner Alerts and Operations

Status: shadow/manual-review only
Order authority: disabled

## One-time administrator setup

Run from an elevated PowerShell prompt:

```powershell
Set-Location C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\register_trading_alert_system.ps1
```

The master setup registers and verifies 15 relevant Task Scheduler entries under
`\VibeTrade\`:

- MES ORB v2 entry and resolve
- MES reopen v2 entry and resolve
- MES v2 delayed Databento regrade
- Equity ORB Scout v1 entry and resolve
- Equity ORB Scout v2 entry and resolve
- MNQ SMT/CISD four-ablation family cycle every completed five-minute RTH bar
- MNQ SMT/CISD delayed Databento regrade at 00:45 CT daily
- HMM regime producer at 08:40 CT on weekdays
- System heartbeat at 09:00, 12:00, and 15:30 CT
- Sunday preflight at 20:00 CT
- Deterministic shadow EOD check-in at 17:07 CT on weekdays

It also refreshes the HMM, catalyst, and bot-status producers, runs import-only
scanner smoke checks, and sends a registration confirmation when Discord is
configured.

## Discord configuration

The notifier reads `DISCORD_WEBHOOK_URL` from the process environment first,
then from `agent/.env`. The webhook is never printed or included in reports.
Only official HTTPS Discord webhook URLs are accepted. Discord mentions are
disabled so scanner-derived text cannot trigger `@everyone` or role pings.

Entry alerts include the top 20 qualified setups with direction, observed proxy
entry, stop, T1, T2, and grade. Resolve alerts include setups scanned, resolved
count, wins/losses/flats, top net movers, and exit reasons.

## Health and automatic halts

Scanner state is stored under:

```text
%USERPROFILE%\.vibe-trading\health\shadow-scanners\
```

Three consecutive failures create `<scanner>.halt`. A halted scanner exits on
its next scheduled fire. Inspect the matching JSON state before clearing it.

After correcting the cause, clear one halt deliberately:

```powershell
python -c "from scripts.shadow_ops import clear_halt; print(clear_halt('mes-orb-v2'))"
python -c "from scripts.shadow_ops import clear_halt; print(clear_halt('mes-reopen-v2'))"
python -c "from scripts.shadow_ops import clear_halt; print(clear_halt('equity-orb-scout-v1'))"
python -c "from scripts.shadow_ops import clear_halt; print(clear_halt('equity-orb-scout-v2'))"
```

The MES ORB scanner continues to reject stale/missing HMM context. The wrapper
sends a specific Discord alert for that skip. The heartbeat marks HMM stale at
more than 72 hours, catalyst data stale at more than 36 hours, and the
Databento capability/MNQ evidence reports stale at more than 30 hours.

## Databento evidence boundary

The configured account currently supports historical `GLBX.MDP3` retrieval but
the live CME gateway reports `live_data_license_required`. The system therefore
keeps timely MNQ alerts labeled as non-executable proxy discovery. At 00:45 CT,
after the current historical availability delay, the regrader:

1. independently rebuilds each signal from raw MNQ/NQ/MES/ES one-minute bars;
2. applies the frozen evidence-only regime labeler;
3. reconstructs the full MNQ MBO book from its midnight snapshot;
4. uses ask/bid for long entry/exit and bid/ask for short entry/exit;
5. appends only integrity-complete post-preregistration outcomes to promotion evidence.

The task estimates cost before every uncached download, attempts at most four
plans, and enforces a $5.00 aggregate daily ceiling. Cached requests cost no
additional allowance. It alerts on attempted regrades and fails closed on
entitlement, range, contract, snapshot, gap, spread, or timestamp errors.

If a Databento live CME license is later activated, the daily capability probe
will change the dashboard status automatically. A separate reviewed live-stream
collector with replay/backfill and deduplication is still required before live
MBO can replace proxy discovery; a successful license probe alone never changes
evidence eligibility or order authority.

## File-drop kill switch

Create this exact file to stop the MES v2, MNQ family, equity scout, and Databento regraders
work on their next fire:

```powershell
New-Item -ItemType File -Path C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\KILL_SWITCH
```

Resume only after review:

```powershell
Remove-Item -LiteralPath C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\KILL_SWITCH
```

This repository-root switch does not change the IWM options bot body. The IWM
bot separately uses `OPTIONS_LIVE_EXECUTION_ENABLED`, its execution guard, and
the existing portfolio kill-switch controls. No Discord slash command is
installed; the local file drop avoids adding an authenticated public command
surface. Heartbeat, preflight, and EOD monitoring remain active so Discord can
report that the kill switch is engaged.

## Manual checks

```powershell
python scripts\shadow_system_heartbeat.py
uv run --no-project --with yfinance --with pandas --with numpy python scripts\sunday_shadow_preflight.py
Get-ScheduledTask -TaskPath "\VibeTrade\" | Where-Object TaskName -Match "Mes|Mnq|EquityOrb|ShadowSystem|SundayShadow|EodShadow"
```

All components in this document are monitoring or shadow evidence systems:

```text
execution_enabled=false
can_submit_orders=false
```
