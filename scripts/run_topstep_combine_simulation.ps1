Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

python strategies\topstep_combine_simulator.py `
    --dataset examples\mes_v0_1m_2022-01-01_2026-07-19_rth.csv `
    --output data\topstep_combine_simulation.json `
    --simulations 5000 `
    --max-sessions 252

exit $LASTEXITCODE
