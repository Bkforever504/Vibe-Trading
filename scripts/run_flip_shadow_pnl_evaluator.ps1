$ErrorActionPreference = "Stop"

$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
Set-Location $repo
$env:PYTHONPATH = $repo

python scripts\resolve_fibonacci_shadow_plans.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python scripts\flip_shadow_pnl_evaluator.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python scripts\accelerated_bot_learning_report.py --print
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python scripts\self_improving_strategy_verifier.py --print
exit $LASTEXITCODE
