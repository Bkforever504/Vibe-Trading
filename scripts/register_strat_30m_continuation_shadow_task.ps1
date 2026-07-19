$ErrorActionPreference = "Stop"
$taskName = "\VibeTrade\Strat30mContinuationShadow"
$runner = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\scripts\run_strat_30m_continuation_shadow.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NonInteractive -File `"$runner`""
$start = [datetime]::Today.AddHours(9).AddMinutes(2)
$triggers = @(0..23 | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $start.AddMinutes($_ * 15) })
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -StartWhenAvailable
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers -Settings $settings -RunLevel Limited -Force
Write-Host "Registered: $taskName"
