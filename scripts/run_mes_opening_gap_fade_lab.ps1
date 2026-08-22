$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

python research/mes_opening_gap_fade_lab.py `
    --csv examples/mes_v0_1m_2022-01-01_2026-07-19_rth.csv `
    --out data/mes_opening_gap_fade_results.json `
    --combine-simulations 2000

if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
