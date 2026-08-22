$ErrorActionPreference = "Continue"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# Read-only evidence pipeline. None of these programs has an order endpoint.
uv run --no-project python research\topstep_prior_date_router.py
uv run --no-project python scripts\topstepx_trade_reconciliation.py --output data\topstepx_practice_reconciliation.json
uv run --no-project python scripts\topstep_readiness_report.py

exit 0

