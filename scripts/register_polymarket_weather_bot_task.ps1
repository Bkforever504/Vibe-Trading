$ErrorActionPreference = "Stop"

$taskName = "\VibeTrade\PolymarketWeatherBot"
$scriptPath = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\scripts\run_polymarket_weather_bot.ps1"
$command = "powershell.exe -NonInteractive -ExecutionPolicy Bypass -File `"$scriptPath`""

schtasks.exe /Create /TN $taskName /TR $command /SC MINUTE /MO 15 /F | Out-Host
Write-Host "Registered: $taskName (paper-only, every 15 minutes)"
