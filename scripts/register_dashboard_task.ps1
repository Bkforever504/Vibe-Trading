param(
    [string]$TaskName = "VibeTradingDashboardGenerator",
    [string]$TaskPath = "\VibeTrade\",
    [string]$At = "20:10"
)

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Runner = Join-Path $Repo "scripts\run_generate_dashboard.ps1"
$LogDir = Join-Path $env:USERPROFILE ".vibe-trading\logs"
New-Item -ItemType Directory -Force $LogDir | Out-Null

$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Runner`" >> `"$LogDir\dashboard-generator.log`" 2>&1"

$Trigger = New-ScheduledTaskTrigger -Daily -At $At
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

Register-ScheduledTask `
    -TaskName $TaskName `
    -TaskPath $TaskPath `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Generate the static Vibe Trading dashboard after the EOD report stack." `
    -Force

Write-Host "Registered $TaskPath$TaskName at $At. Output: $env:USERPROFILE\.vibe-trading\dashboard.html"
