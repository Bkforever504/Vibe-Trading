# Repository intake: local AI and market-agent projects

Date: 2026-09-07

## Decision

Adopt small, auditable patterns; do not import any project wholesale.

| Project | Decision | Useful idea | Rejected risk |
|---|---|---|---|
| LocalAI | Optional adapter implemented, disabled by default | OpenAI-compatible loopback inference as an alternative to Ollama | A second simultaneous LLM vote would add latency and correlated model risk |
| TradingAgents | Pattern-only | Bull/bear critic separation, checkpointed research, structured risk challenge | LLM debate is nondeterministic and must never originate, approve, size, or execute a trade |
| ai-market | Do not integrate runtime | Prediction ledger, A/B comparison, agent attribution | Its documented simulated-price fallback violates fail-honest market-data policy; repository history and claims require independent validation |
| StockSight | Do not integrate runtime | Provenance-stamped sentiment evidence | Twitter-era NLP/Elasticsearch stack is dated and sentiment is too weak for trigger authority |

## Implemented consequences

- `agent/src/providers/localai_shadow_critic.py`: loopback-port-8080-only, schema-constrained, veto-only LocalAI adapter.
- `config/localai_shadow_critic.json`: disabled alternate backend; it is not run together with Ollama.
- `agent/src/research/blsh_bakeoff.py`: common feature fabric, prediction attribution, cross-sectional outputs, forward-return join and paired statistical comparison.
- LLM-derived material remains a post-delivery critic and cannot remove deterministic blockers.
- Market-data gaps remain unavailable; no simulated or cached synthetic price fallback was adopted.

## Sources

- https://github.com/mudler/LocalAI
- https://github.com/TauricResearch/TradingAgents
- https://github.com/dtquocbao/ai-market
- https://github.com/shirosaidev/stocksight
