$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

uv run --no-project python scripts\edge_recovery_report.py
