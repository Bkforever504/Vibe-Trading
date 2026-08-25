$ErrorActionPreference = "Stop"
if ((Get-TimeZone).Id -ne "Central Standard Time") {
    throw "MNQ Databento task registration requires Central Standard Time."
}

$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$runner = "$repo\scripts\run_mnq_smt_family_databento_regrader.ps1"
$service = New-Object -ComObject "Schedule.Service"
$service.Connect()
$rootFolder = $service.GetFolder("\")
try { $null = $service.GetFolder("\VibeTrade") } catch { $null = $rootFolder.CreateFolder("VibeTrade") }

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$runner`""
$trigger = New-ScheduledTaskTrigger -Daily -At "00:45"
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 60) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable

Register-ScheduledTask `
    -TaskName "MnqSmtDatabentoRegrade" `
    -TaskPath "\VibeTrade\" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -RunLevel Limited `
    -Description "Cost-capped delayed GLBX.MDP3 OHLCV reproduction plus MNQ MBO shadow regrade; no orders." `
    -Force | Out-Null

Write-Host "Registered \VibeTrade\MnqSmtDatabentoRegrade daily at 00:45 CT."
Write-Host "execution_enabled=false; can_submit_orders=false; daily cost cap USD 5.00."
