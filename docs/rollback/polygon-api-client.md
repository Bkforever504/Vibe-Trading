# Polygon options-chain rollback

This integration is read-only and has no order authority.

1. Set `providers.polygon_options.enabled` to `false` in `config/paid_api_budget.json`.
2. Set `preferred_options_chain_provider` to `databento` in `config/options_bot.json`.
3. Remove `massive==2.8.0` (the maintained official Polygon/Massive SDK) from `pyproject.toml` and regenerate `uv.lock`.
4. Delete `agent/data_providers/polygon_options_client.py` and remove `polygon` from the router priority.

Retain `~/.vibe-trading/data/polygon_options_call_ledger.jsonl` and weekly cost reports for audit history.
