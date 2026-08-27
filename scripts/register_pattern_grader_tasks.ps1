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
    "/SC", "DAILY", "/ST", "08:35", "/RI", "5", "/DU", "06:30",
    "/RL", "LIMITED", "/F"
)

# Close-of-day aggregation was previously scheduled at 15:30 CT (an hour later
# than the regular 15:00 CT cash close plus a five-minute settle window). That
# left the resolver waiting on bars that already existed and dropped the entire
# outcome batch onto a single 15:35 window. Aggregator now fires at 15:05 CT
# and the resolver at 15:10 CT so end-of-day evidence lands before the evening
# review chain. market_schedule_alignment.py owns the same expected times.
Register-NativeTask @(
    "/Create", "/TN", "$Folder\PatternGrader-Aggregator",
    "/TR", $TaskCommand,
    "/SC", "WEEKLY", "/D", "MON,TUE,WED,THU,FRI", "/ST", "15:05",
    "/RL", "LIMITED", "/F"
)

Write-Host "Registered $Folder PatternGrader-Scanner-Intraday (08:35) and PatternGrader-Aggregator (15:05). Read-only pattern evidence; no orders."
