# Verified Trader Intake

This pipeline collects external trader observations without giving any source
order authority. It is a research and shadow-replay system.

## What Is Ready

- append-only canonical evidence journal
- deterministic deduplication
- consent and provenance gates
- X API research-log adapter
- TradingView webhook adapter and receiver
- Collective2-style JSON signal adapter
- SnapTrade activity JSON adapter
- broker CSV and manual-export adapters
- credential redaction
- evidence, completeness, and timeliness scoring
- safe report and compatibility exports

The code does not contain an order client.

## Canonical Paths

- Journal: `data/verified_trader_evidence_log.jsonl`
- Report: `~/.vibe-trading/reports/verified-trader-evidence.json`
- Safe profiles export: `~/.vibe-trading/verified-trader-profiles.json`
- Safe signals export: `~/.vibe-trading/verified-trader-signals.json`

The safe signals export includes only alerts carrying a separately captured
point-in-time market price. The pipeline never pretends that the trader's
posted price is still available.

## Import Existing X Research

```powershell
python scripts/verified_trader_intake.py import `
  --source-type x_api `
  --source-id x-api-paid-research `
  --input data/x_spy_research_intake_log.jsonl
```

These records are context-only regardless of author verification or engagement.

## Import A Covered Broker Export

Use `broker_fills_template.csv` and replace the example rows. Do not include
account numbers, credentials, or personally identifying information. Use a
unique `source-id` for each immutable export. The command hashes the complete
file, counts its fill/outcome records, and appends the coverage manifest in the
same operation. The attestation means the export covers the requested period
and includes losses; do not use it for a filtered or partial export.

```powershell
python scripts/verified_trader_intake.py import-covered `
  --source-type broker_csv `
  --source-id broker-export-2026-07 `
  --consent-ref signed-agreement-id `
  --trader-id anonymized-trader-id `
  --account-alias non-sensitive-local-alias `
  --requested-start 2026-01-01T00:00:00Z `
  --requested-end 2026-07-31T23:59:59Z `
  --coverage-start 2026-01-01T00:00:00Z `
  --coverage-end 2026-07-31T23:59:59Z `
  --attest-complete-losses `
  --input C:\path\to\sanitized-fills.csv
```

## Import SnapTrade Activities

Export the JSON returned by the read-only account-activities endpoint. The
account owner must explicitly consent.

```powershell
python scripts/verified_trader_intake.py import-covered `
  --source-type snaptrade_activity `
  --source-id snaptrade-export-2026-07 `
  --consent-ref signed-agreement-id `
  --trader-id anonymized-trader-id `
  --account-alias non-sensitive-local-alias `
  --requested-start 2026-01-01T00:00:00Z `
  --requested-end 2026-07-31T23:59:59Z `
  --coverage-start 2026-01-01T00:00:00Z `
  --coverage-end 2026-07-31T23:59:59Z `
  --attest-complete-losses `
  --input C:\path\to\snaptrade-activities.json
```

## Import Collective2 Signals

```powershell
python scripts/verified_trader_intake.py import `
  --source-type collective2_signal `
  --source-id collective2-system-alias `
  --input C:\path\to\signals.json
```

API access and any subscription must be approved separately. The adapter makes
no network or paid request.

## TradingView Webhook

Set three local environment variables:

```powershell
$env:VERIFIED_TRADER_WEBHOOK_TOKEN = "<long-random-opaque-token>"
$env:VERIFIED_TRADER_SOURCE_ID = "tradingview-trader-alias"
$env:VERIFIED_TRADER_CONSENT_REF = "signed-agreement-id"
$env:VERIFIED_TRADER_TRADER_ID = "anonymized-trader-id"
$env:VERIFIED_TRADER_AUTO_QUOTE = "1"
```

Run:

```powershell
.\scripts\run_verified_trader_webhook.ps1
```

The local endpoint is:

```text
POST /webhooks/tradingview/<opaque-token>
```

TradingView needs a public HTTPS endpoint for internet delivery. Do not expose
the receiver until TLS, token rotation, request limits, and deployment logging
have been reviewed. Never put brokerage credentials in an alert.

When Alpaca market-data credentials are available, the receiver captures a
separate latest stock trade or option-side quote at receipt time. Set
`VERIFIED_TRADER_AUTO_QUOTE=0` to disable this read-only join. A failed quote
never fabricates a price; the alert remains a replay candidate but not a
live-shadow record.

## Build Report

```powershell
python scripts/verified_trader_intake.py report --print
```

The optional scheduled report can be registered as Administrator:

```powershell
.\scripts\register_verified_trader_report_task.ps1
```

It performs no network access and places no orders.

## Advancement Rule

Thirty clean outcomes are only the beginning of review. A trader still needs
cost stress, delay stress, outlier removal, multi-regime stability, independent
adversarial review, and human approval. No report promotes itself.
