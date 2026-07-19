$TaskName = "VibeTradingNinjaTraderMESSim"
$WorkingDir = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$LogDir = "$env:USERPROFILE\.vibe-trading\logs"
$UvPath = (Get-Command uv -ErrorAction Stop).Source

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$Args = "run --no-project --with yfinance python scripts/run_ninjatrader_mes_sim.py --execute-sim"
$Action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c cd /d `"$WorkingDir`" && `"$UvPath`" $Args >> `"$LogDir\ninjatrader-mes-sim.log`" 2>&1"
$Trigger = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
    -At "11:05AM"
$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([TimeSpan]::FromMinutes(10)) `
    -MultipleInstances IgnoreNew
$Principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Sim101 only: one-contract MES 1h pullback candidate with 40/80 ATM bracket." | Out-Null

Write-Host "Registered $TaskName for weekdays at 11:05 AM Central (12:05 PM Eastern)."
