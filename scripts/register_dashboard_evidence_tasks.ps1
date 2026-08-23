param([string]$PythonPath = "")

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$Python = if ($PythonPath) { $PythonPath } else { (Get-Command python -ErrorAction Stop).Source }
$IntradayRunner = Join-Path $PSScriptRoot "run_dashboard_intraday_evidence.ps1"
$PostCloseRunner = Join-Path $PSScriptRoot "run_dashboard_evidence_chain.ps1"

function Register-NativeTask([string[]]$Arguments) {
    & schtasks.exe @Arguments | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "schtasks.exe failed with exit code $LASTEXITCODE" }
}

$IntradayCommand = "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$IntradayRunner`" -PythonPath `"$Python`""
$PostCloseCommand = "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$PostCloseRunner`" -PythonPath `"$Python`""

Register-NativeTask @(
    "/Create", "/TN", "VibeTradingDashboardEvidenceIntraday",
    "/TR", $IntradayCommand,
    "/SC", "DAILY", "/ST", "08:25", "/RI", "15", "/DU", "08:15",
    "/RL", "LIMITED", "/F"
)
Register-NativeTask @(
    "/Create", "/TN", "VibeTradingDashboardEvidencePostClose",
    "/TR", $PostCloseCommand,
    "/SC", "WEEKLY", "/D", "MON,TUE,WED,THU,FRI", "/ST", "16:45",
    "/RL", "LIMITED", "/F"
)

Write-Host "Registered read-only dashboard evidence tasks. No order authority or credentials are stored in task arguments."
