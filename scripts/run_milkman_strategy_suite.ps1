$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

python research\milkman_strategy_suite.py --print
exit $LASTEXITCODE
