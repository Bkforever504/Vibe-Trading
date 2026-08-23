param(
    [string]$TaskPath = "\VibeTrade\",
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"
$Runner = Join-Path $PSScriptRoot "run_pattern_grader_pipeline.ps1"
$Python = if ($PythonPath) { $PythonPath } else { (Get-Command python -ErrorAction Stop).Source }
$Folder = $TaskPath.TrimEnd("\")
$TaskCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$Runner`" -PythonPath `"$Python`""

function Register-NativeTask([string[]]$Arguments) {
    & schtasks.exe @Arguments | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "schtasks.exe failed with exit code $LASTEXITCODE"
    }
}

# Windows PowerShell does not expose repetition on a Weekly trigger on all
# supported hosts. The native DAILY repetition is stable; the runner itself
# has a fail-closed Saturday/Sunday guard.
Register-NativeTask @(
    "/Create", "/TN", "$Folder\PatternGrader-Scanner-Intraday",
    "/TR", $TaskCommand,
    "/SC", "DAILY", "/ST", "08:25", "/RI", "5", "/DU", "08:00",
    "/RL", "LIMITED", "/F"
)

Register-NativeTask @(
    "/Create", "/TN", "$Folder\PatternGrader-Aggregator",
    "/TR", $TaskCommand,
    "/SC", "WEEKLY", "/D", "MON,TUE,WED,THU,FRI", "/ST", "16:35",
    "/RL", "LIMITED", "/F"
)

Write-Host "Registered $Folder PatternGrader-Scanner-Intraday and PatternGrader-Aggregator. Read-only pattern evidence; no orders."
