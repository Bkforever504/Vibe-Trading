$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

python scripts/public_strategy_replication.py verify
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

python scripts/public_strategy_replication.py report
exit $LASTEXITCODE
