$ErrorActionPreference = "Stop"

$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
Set-Location $repo

uv run --no-project python scripts\flip_shadow_pnl_evaluator.py
python scripts\accelerated_bot_learning_report.py --print
python scripts\self_improving_strategy_verifier.py --print
