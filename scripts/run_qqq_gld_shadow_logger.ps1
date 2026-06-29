# QQQ/GLD Rotation Shadow Logger
# Runs weekly before market open.
# Shadow only - no trading, no Alpaca calls.
#
# Schedule via Task Scheduler:
#   Program: powershell.exe
#   Args: -NonInteractive -File "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\scripts\run_qqq_gld_shadow_logger.ps1"
#   Trigger: Weekly Monday at 08:05 CT

Set-Location "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"

Write-Host "Running QQQ/GLD shadow logger..."
uv run --no-project --with alpaca-py --with pandas python scripts\qqq_gld_shadow_logger.py

Write-Host ""
Write-Host "Running QQQ/GLD shadow report..."
uv run --no-project python scripts\qqq_gld_shadow_report.py
