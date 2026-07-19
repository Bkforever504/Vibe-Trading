$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

uv run --no-project python scripts\micro_account_readiness_report.py
