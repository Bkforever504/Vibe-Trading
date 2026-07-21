$ErrorActionPreference = "Stop"
Set-Location "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
uv run --no-project python scripts/edge_trial_ledger.py report
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
uv run --no-project python scripts/build_active_trial_manifest.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
uv run --no-project python scripts/adversarial_strategy_audit.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
uv run --no-project python scripts/self_learning_edge_loop.py --print
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
uv run --no-project python scripts/self_improving_strategy_verifier.py --print
exit $LASTEXITCODE
