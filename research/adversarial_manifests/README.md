# Adversarial Strategy Manifests

One JSON manifest is required for every strategy or symbol seeking promotion.
The strategy builder must not be the reviewer. Raw return arrays are required;
summary screenshots and win-rate claims are insufficient.

```json
{
  "subject_id": "SPY",
  "strategy_version": "frozen-v1",
  "builder_id": "builder-agent-or-person",
  "reviewer_id": "independent-reviewer",
  "preregistered": true,
  "execution_delay_bars": 1,
  "operation_count": 8,
  "trials_considered": 12,
  "timestamp_audit": {"passed": true, "evidence": "path/to/audit.md"},
  "backtest_forward_parity": {"passed": true, "evidence": "path/to/parity.json"},
  "returns": {
    "final": [0.01, -0.005],
    "forward": [0.008, -0.003],
    "cost_2x": [0.007, -0.004],
    "cost_3x": [0.005, -0.005]
  },
  "parameter_neighbors": [
    {"parameters": {"lookback": 20}, "returns": [0.01, -0.004]}
  ],
  "regimes": {
    "bull": [0.01, -0.002],
    "bear": [0.004, -0.003],
    "sideways": [0.003, -0.002]
  },
  "walk_forward_folds": [
    {"fold": 1, "returns": [0.01, -0.003]}
  ]
}
```

Return units must be consistent within a manifest. Use realized net returns
after the declared fill, spread, slippage, and commission model. At least 30
final and 30 forward observations are required. Missing evidence fails closed.

Run:

```powershell
uv run --no-project python scripts/adversarial_strategy_audit.py --print
uv run --no-project python scripts/self_learning_edge_loop.py --print
uv run --no-project python scripts/self_improving_strategy_verifier.py --print
```

Passing the audit permits human promotion review only. It never enables orders.
