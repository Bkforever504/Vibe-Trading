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
uv run --no-project python scripts/flip_shadow_time_bucket_report.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
uv run --no-project python scripts/shadow_consensus_blocker_audit.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
uv run --no-project python scripts/shadow_logger_audit.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
uv run --no-project python scripts/self_improving_strategy_verifier.py --print
exit $LASTEXITCODE
