param([switch]$Window)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
if ((Get-Date).DayOfWeek -in @('Saturday', 'Sunday')) { exit 0 }
Set-Location "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$logDir = Join-Path $HOME ".vibe-trading\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

do {
    & python scripts\broker_reconciliation_daemon.py 2>&1 | Tee-Object -FilePath (Join-Path $logDir "broker-reconciliation.log") -Append
    if (-not $Window) {
        if ($LASTEXITCODE -ne 0) { throw "Broker reconciliation exited $LASTEXITCODE" }
        break
    }
    $now = Get-Date
    $end = Get-Date -Hour 16 -Minute 15 -Second 0
    if ($now -ge $end) { break }
    $next = $now.AddMinutes(5 - ($now.Minute % 5)).AddSeconds(-$now.Second).AddMilliseconds(-$now.Millisecond)
    $sleepSeconds = [Math]::Max(1, [int][Math]::Ceiling(($next - $now).TotalSeconds))
    Start-Sleep -Seconds $sleepSeconds
} while ($true)
