$ErrorActionPreference = "Stop"
$taskName = "\VibeTrade\AdversarialSelfLearningLoop"
$scriptPath = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\scripts\run_adversarial_self_learning_loop.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NonInteractive -ExecutionPolicy Bypass -File `"$scriptPath`""
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "16:10"
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 15) -StartWhenAvailable -RunOnlyIfNetworkAvailable:$false
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -RunLevel Limited -Force | Out-Null
Write-Host "Registered: $taskName"
