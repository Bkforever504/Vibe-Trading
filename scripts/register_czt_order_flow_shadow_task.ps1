$ErrorActionPreference = "Stop"
$taskName = "\VibeTrade\CZTOrderFlowShadow"
$runner = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\scripts\run_czt_order_flow_shadow.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NonInteractive -File `"$runner`""
$start = [datetime]::Today.AddHours(8).AddMinutes(45)
$triggers = @(
    0..24 | ForEach-Object {
        New-ScheduledTaskTrigger -Daily -At $start.AddMinutes($_ * 15)
    }
)
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -StartWhenAvailable
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers -Settings $settings -RunLevel Limited -Force
Write-Host "Registered: $taskName"
