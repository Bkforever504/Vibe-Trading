# Polygon/Massive options-chain provider

The upstream Polygon.io service rebranded to Massive.com in October 2025. The
official Python repository moved from `polygon-io/client-python` to
`massive-com/client-python`, and the maintained distribution/import is now
`massive`. This integration pins `massive==2.8.0` rather than the legacy
`polygon-api-client`; the legacy package constrained `certifi` below 2026 and
would have downgraded the repository's certificate bundle.

The adapter is read-only and limited to shadow research and end-of-day chain
checks. It cannot authorize or submit orders. Provider failures return explicit
statuses, and the ledger stores only normalized metadata plus a SHA-256 response
hash—not raw payloads or credentials.

Primary upstream references:

- https://github.com/massive-com/client-python
- https://pypi.org/project/massive/
