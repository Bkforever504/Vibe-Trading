# Public Strategy Replication League

This directory contains operator templates for the research-only pipeline in
`scripts/public_strategy_replication.py`.

## Workflow

1. Capture a complete public source with lawful access.
2. Normalize its pre-entry calls through `scripts/verified_trader_intake.py`.
3. Translate the disclosed strategy into a deterministic rule file.
4. Register the frozen rule in the hash-chained replication ledger.
5. Snapshot eligible signals under that exact rule version.
6. Import a complete source-coverage manifest.
7. Reconstruct entries and exits from point-in-time OPRA executable quotes.
8. Generate the league report and inspect every blocker.

```powershell
python scripts/public_strategy_replication.py register-rules `
  --input research/public_strategy_replication/strategy_rule.template.json

python scripts/public_strategy_replication.py snapshot-signals `
  --verified-journal data/verified_trader_evidence_log.jsonl `
  --rule-id replace_with_public_rule_id `
  --version 1.0.0

python scripts/public_strategy_replication.py import-coverage `
  --input research/public_strategy_replication/coverage_manifest.template.json

python scripts/public_strategy_replication.py import-outcomes `
  --input research/public_strategy_replication/executable_outcome.template.json

python scripts/public_strategy_replication.py verify
python scripts/public_strategy_replication.py report --print
```

The templates are not active strategies and do not establish an edge. Replace
all placeholders from independently captured evidence before importing them.

## Operational Boundaries

- Never infer a full strategy from a winning screenshot.
- Never enter self-reported PnL as a reconstructed outcome.
- Never backdate `observed_at` to improve apparent latency.
- Never omit losing, stale, unfilled, deleted, or conflicting calls.
- Never reuse a rule version after changing its logic.
- Never connect this module to a broker client or order endpoint.
