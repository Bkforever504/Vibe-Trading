Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
. (Join-Path $PSScriptRoot "resolve_vibe_python.ps1")
$Python = Get-VibePython

if (Test-Path -LiteralPath ".\KILL_SWITCH") {
    Write-Host "KILL_SWITCH active; MNQ Databento regrader skipped."
    exit 0
}

try {
    & $Python scripts\databento_mes_capability_probe.py
    if ($LASTEXITCODE -ne 0) { throw "Databento capability probe exited $LASTEXITCODE" }
    $raw = & $Python scripts\mnq_smt_family_databento_regrader.py --download --max-mbo-cost 4.50 --max-ohlcv-cost 0.15 --max-daily-cost 5.00 --max-plans 4
    if ($LASTEXITCODE -ne 0) { throw "regrader exited $LASTEXITCODE" }
    Write-Host $raw
    $report = $raw | ConvertFrom-Json
    & $Python scripts\mnq_smt_family_evidence_status.py
    if ($LASTEXITCODE -ne 0) { throw "evidence status exited $LASTEXITCODE" }
    & $Python scripts\mes_v2_evidence_status.py
    if ($LASTEXITCODE -ne 0) { throw "MES evidence status exited $LASTEXITCODE" }
    if ([int]$report.attempted_count -gt 0) {
        $message = "MNQ Databento regrade: attempted=$($report.attempted_count), qualified=$($report.qualified_count), excluded=$($report.excluded_count), failed_closed=$($report.failed_closed_count), estimated_cost=$($report.daily_estimated_download_cost_usd). No orders."
        python -m agent.notifier --message $message
    }
} catch {
    python -m agent.notifier --message "MNQ Databento regrader FAILED CLOSED. No orders. Check workstation logs."
    throw
}
