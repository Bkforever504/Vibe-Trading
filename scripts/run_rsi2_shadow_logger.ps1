Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
uv run --no-project --with alpaca-py --with pandas --with numpy python scripts\rsi2_shadow_logger.py
uv run --no-project --with pandas --with numpy python scripts\rsi2_shadow_report.py
uv run --no-project --with alpaca-py --with pandas --with numpy python scripts\qqq_mean_reversion_shadow.py
uv run --no-project --with numpy python scripts\qqq_mean_reversion_shadow_report.py
