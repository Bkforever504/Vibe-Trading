$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

uv run --no-project python scripts\topstepx_practice_probe.py
