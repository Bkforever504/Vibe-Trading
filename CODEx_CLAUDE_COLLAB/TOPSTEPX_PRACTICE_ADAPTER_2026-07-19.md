# TopstepX Practice Adapter - 2026-07-19

## Built

- `strategies/topstepx_practice_adapter.py`
- `scripts/topstepx_practice_probe.py`
- `rules/prop_firms/topstep_practice_api.json`
- `agent/tests/test_topstepx_practice_adapter.py`

## Safety Boundary

The adapter is read-only by default. Entry requires an exact account ID allowlist, an API-returned account name containing the standalone `PRACTICE` marker, the exact `PRACTICE_ONLY_CONFIRMED` execution phrase, the exact `PERSONAL_DEVICE_CONFIRMED` local-device phrase, one MES maximum, 40 stop ticks maximum, the 9:45-11:30 AM ET window, a passing prop-rule gate, no open position/order, no prior accepted or uncertain entry that session, and no global manual-reset block.

There is no funded or Trading Combine override. API order requests use `live: false` data discovery and attach a stop bracket and take-profit bracket to the entry. An uncertain submission is journaled and blocks automatic retry. The emergency flatten path remains available while the global entry kill switch is active.

## Credential Sequence

1. Activate a Topstep Trading Combine and its free Practice account.
2. Activate ProjectX API access and create the TopstepX API key.
3. Add `TOPSTEPX_USERNAME` and `TOPSTEPX_API_KEY` to `agent/.env`.
4. Run `scripts/run_topstepx_practice_probe.ps1`.
5. Copy the returned Practice candidate ID into `TOPSTEPX_PRACTICE_ACCOUNT_ID`.
6. Run the probe again and require `practice_read_only_ready` plus complete MES bars.
7. Keep both execution confirmations blank until historical and read-only validation passes.

## Current Boundary

No credentials are present yet, no real ProjectX request has been made, and no order runner or strategy-to-order bridge has been enabled. The adapter is ready for read-only credential discovery.

## Official References

- https://gateway.docs.projectx.com/docs/getting-started/authenticate/authenticate-api-key/
- https://gateway.docs.projectx.com/docs/getting-started/connection-urls/
- https://gateway.docs.projectx.com/docs/api-reference/account/search-accounts/
- https://gateway.docs.projectx.com/docs/api-reference/market-data/retrieve-bars/
- https://gateway.docs.projectx.com/docs/api-reference/order/order-place/
- https://gateway.docs.projectx.com/docs/api-reference/positions/search-open-positions/
- https://help.topstep.com/en/articles/11187768-topstepx-api-access
- https://help.topstep.com/en/articles/8284134-practice-account
