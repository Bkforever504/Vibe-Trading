Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"

# At most one plan is attempted per invocation. The aggregate daily ceiling is
# $2.25 across all invocations; cached requests do not consume that allowance.
# No broker/order API is imported anywhere in this pipeline.
uv run --no-project --with databento --with pandas --with numpy python scripts\mes_v2_databento_regrader.py --download --max-mbo-cost 2.00 --max-ohlcv-cost 0.25 --max-daily-cost 2.25 --max-plans 1
uv run --no-project --with pandas --with numpy python scripts\shadow_outcome_resolver.py
uv run --no-project --with pandas --with numpy python research\multi_lane_replay.py --output data\mes_v2_forward_replay.json
uv run --no-project --with pandas --with numpy python scripts\promotion_gate.py data\mes_v2_forward_replay.json
uv run --no-project --with pandas --with numpy python scripts\mes_v2_evidence_status.py
