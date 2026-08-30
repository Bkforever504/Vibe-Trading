$ErrorActionPreference = "Stop"
Set-Location "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
uv run --no-project --with pandas python scripts/flip_exit_policy_comparison.py --print
