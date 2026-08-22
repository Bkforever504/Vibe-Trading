$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
uv run --no-project --with pandas --with pyarrow python research\market_scenario_curriculum.py
