$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
uv run --no-project --with yfinance --with pandas python scripts/flip_decision_missed_banger_review.py
if ($LASTEXITCODE -ne 0) {
    throw "Flip decision missed-banger review failed with exit code $LASTEXITCODE"
}
