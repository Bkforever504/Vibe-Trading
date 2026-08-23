param(
    [string]$PythonPath = "",
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = if ($PythonPath) { $PythonPath } else { (Get-Command python -ErrorAction Stop).Source }
$StateDir = Join-Path $env:USERPROFILE ".vibe-trading"
$ReportDir = Join-Path $StateDir "reports"
$LogDir = Join-Path $StateDir "logs"
$LogPath = Join-Path $LogDir "dashboard-evidence-chain.log"
$SessionDate = Get-Date -Format "yyyy-MM-dd"
$Failures = [System.Collections.Generic.List[string]]::new()

New-Item -ItemType Directory -Force -Path $ReportDir, $LogDir | Out-Null
Set-Location -LiteralPath $RepoRoot

if (-not $Force -and (Get-Date).DayOfWeek -in @("Saturday", "Sunday")) {
    "$(Get-Date -Format o) weekend skip; execution_enabled=false can_submit_orders=false" |
        Add-Content -LiteralPath $LogPath -Encoding utf8
    exit 0
}

function Invoke-ReadOnlyProducer {
    param([string]$Name, [string[]]$Arguments, [int[]]$AcceptedExitCodes = @(0))
    & $Python @Arguments *>> $LogPath
    $Code = $LASTEXITCODE
    if ($Code -notin $AcceptedExitCodes) {
        $Failures.Add("$Name exit=$Code")
    }
}

Invoke-ReadOnlyProducer "options-feed" @("scripts\options_feed_qualification.py")
Invoke-ReadOnlyProducer "manual-quality" @("scripts\manual_execution_quality.py")
Invoke-ReadOnlyProducer "broker-fill" @("scripts\broker_fill_observer.py")
# VibeTradingMoveGroundTruth runs the independent, cost-gated provider build at
# 16:30 CT. This 16:45 task consumes its report and never downloads it twice.
"$(Get-Date -Format o) consuming VibeTradingMoveGroundTruth output" |
    Add-Content -LiteralPath $LogPath -Encoding utf8
Invoke-ReadOnlyProducer "detection-scorecard" @("scripts\detection_scorecard.py", "--date", $SessionDate)
Invoke-ReadOnlyProducer "probability-calibration" @("scripts\grade_probability_service.py")
Invoke-ReadOnlyProducer "daily-aplus-review" @("scripts\daily_aplus_review.py", "--date", $SessionDate)
Invoke-ReadOnlyProducer "readiness" @("scripts\dashboard_readiness.py")

"$(Get-Date -Format o) completed failures=$($Failures.Count); execution_enabled=false can_submit_orders=false" |
    Add-Content -LiteralPath $LogPath -Encoding utf8
if ($Failures.Count -gt 0) {
    throw "Dashboard evidence producers failed: $($Failures -join ', ')"
}
