param(
    [ValidateSet("scan", "revalidate")]
    [string]$Mode = "scan"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
Set-Location $repo

if (Test-Path (Join-Path $repo "KILL_SWITCH")) {
    Write-Warning "KILL_SWITCH present. Equity ignition-continuation shadow scan skipped."
    exit 0
}

uv run --no-project --with yfinance --with pandas --with numpy python scripts\equity_ignition_continuation_shadow.py --mode $Mode
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# Fixed priority-universe swing observation. This remains unvalidated,
# shadow-only, and has no broker or live-order authority.
uv run --no-project --with yfinance --with pandas --with numpy python scripts\priority_swing_observation.py --mode $Mode --alert
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
