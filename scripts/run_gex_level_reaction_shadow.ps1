$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir

Set-Location $projectRoot
uv run --no-project --with alpaca-py python scripts/gex_level_reaction_shadow.py --symbol SPY --print
uv run --no-project python research/gex_level_reaction_lab.py
