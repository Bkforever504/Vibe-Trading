# Williams %R Shadow Logger
# Runs daily after market close (15:20 CT / 16:20 ET).
# Shadow only — no trading, no Alpaca calls.
#
# Schedule via Task Scheduler:
#   Program: powershell.exe
#   Args: -NonInteractive -File "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\scripts\run_williams_r_shadow_logger.ps1"
#   Trigger: Daily at 15:20 CT (21:20 UTC), Mon-Fri

Set-Location "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"

Write-Host "Running Williams %R shadow logger..."
uv run --no-project --with alpaca-py --with pandas python scripts\williams_r_shadow_logger.py

Write-Host ""
Write-Host "Running Williams %R shadow report..."
uv run --no-project python scripts\williams_r_shadow_report.py
