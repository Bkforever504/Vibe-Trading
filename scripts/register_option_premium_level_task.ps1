$ErrorActionPreference = "Stop"
$taskName = "\VibeTrade\OptionPremiumLevels"
$runner = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\scripts\run_option_premium_level_logger.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NonInteractive -WindowStyle Hidden -File `"$runner`""
$start = [datetime]::Today.AddHours(8).AddMinutes(40)
$triggers = @(0..3 | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $start.AddMinutes($_ * 15) })
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -StartWhenAvailable
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers -Settings $settings -RunLevel Limited -Force
Write-Host "Registered: $taskName"
