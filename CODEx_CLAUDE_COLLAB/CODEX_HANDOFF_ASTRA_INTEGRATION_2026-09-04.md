# Codex Handoff — Astra Integration as Critic Layer (Capability Under Test)

**Date**: 2026-09-04
**Author**: Claude (spec)
**Executor**: Codex
**Depends on**: `CODEX_HANDOFF_EXECUTION_PRECISION_2026-09-04.md` AND `CODEX_HANDOFF_LEARNING_LOOP_2026-09-04.md` (both must land first — Astra roles consume their outputs)
**Mode**: shadow-only. Astra is evidence-only. No execution authority. No auto-tuning. No parameter mutation.

## Framing

Astra is a new model from Codex. Its capability claims are **vendor-authored** and unverified in this system. This handoff installs Astra as a testable critic layer with rigorous A/B, frozen-sample promotion gate, cost cap, and full prompt/response audit trail. If Astra proves an edge over the existing critic stack, it earns more roles. If it doesn't, it stays disabled without touching the deterministic spine.

**Bright line**: Astra can *observe*, *explain*, *disagree*, and *nominate*. Astra cannot decide, size, route, or execute. Deterministic policy is the sole decision authority (invariant 3).

## Non-negotiable invariants (inherit)

1. `execution_enabled=false`, `can_submit_orders=false` on every Astra-derived record.
2. Astra never mutates config, thresholds, grade cutoffs, or watcher constants.
3. Astra outputs are stored with the full prompt, model_id, temperature, response, tokens, cost, and timestamp — audit trail is non-negotiable.
4. Astra can veto but cannot un-veto. If Astra says "reject", it becomes an additional blocker. If Astra says "approve", the deterministic gate still decides.
5. Cost budget cap enforced. When budget exhausted, all Astra calls fail-honest as `status: "budget_exceeded"`, downstream pipeline continues without Astra.
6. When Astra API unavailable, all pipelines continue unchanged. Astra card emits `status: "missing"`. Never fabricate.
7. `order_authority_invariant` must return `violations=0`.

---

## Workstream 11 — Astra client + audit ledger

**Implement** `scripts/astra_client.py`:

Reads credentials from `agent/.env`:
```
ASTRA_API_KEY=...
ASTRA_ENDPOINT=https://api.codex.example/v1/astra
ASTRA_MODEL_ID=astra-1.0
ASTRA_DAILY_USD_BUDGET=5.00
ASTRA_MAX_LATENCY_SECONDS=8
```

If any missing → `status: "not_configured"` on every call. Pipeline continues.

Client contract:
```python
def call(prompt: str, *, role: str, alert_key: str, temperature: float = 0.0) -> dict:
    """Returns:
    {
      "status": "ok|not_configured|budget_exceeded|timeout|http_<code>|<exception>",
      "content": str | None,
      "structured": dict | None,   # parsed JSON if response was JSON, else None
      "model_id": str,
      "prompt_tokens": int,
      "completion_tokens": int,
      "cost_usd": float,
      "latency_seconds": float,
      "audit_id": str,             # sha256(role|alert_key|prompt|timestamp)
      "attempted_at": "<UTC Z>",
      "execution_enabled": False,
      "can_submit_orders": False,
    }
    """
```

Every call — success, failure, timeout, budget breach — appends to `~/.vibe-trading/data/astra_call_ledger.jsonl`. This ledger is the source of truth for cost, latency, and reproducibility.

Daily budget guard: sum `cost_usd` for today's ET date from ledger before each call. If projected next call would exceed budget → return `budget_exceeded` without calling.

**Test** `agent/tests/test_astra_client.py`:
- Missing env → `not_configured`, no HTTP call attempted.
- Mock over-budget → `budget_exceeded`, no HTTP call.
- Timeout mock → `timeout`, ledger row written.
- Successful call → ledger row with full audit fields.

---

## Workstream 12 — Astra as sixth evidence critic

**Extend** `scripts/governed_shadow_decision.py` `evidence_cards`:

Add a sixth card with role `astra_llm_critic`. Prompt template:

```
You are a market-structure critic. You are NOT the decision authority.
Your output is one of five recommendations plus a one-sentence rationale.
You must respond as strict JSON with keys: recommendation, rationale, confidence.

recommendation ∈ {"reject", "size_down", "observe", "approve", "insufficient_evidence"}
confidence ∈ {"low", "medium", "high"}

Candidate:
symbol={symbol}, direction={direction}, setup={setup}, grade={grade}
trigger={trigger}, stop={stop}, target={target}, bar_completed_at={bar_completed_at}

Evidence bundle:
- technical: {technical_facts}
- recent_regime: {recent_regime_facts}
- consensus: {consensus_facts}
- debate: {debate_facts}
- institutional_confluence: {confluence_facts}

Rules:
- If any independent institutional source contradicts direction, recommend "reject".
- If recent_regime.status is "degraded", recommend at most "observe".
- If evidence bundle is incomplete or self-contradictory, recommend "insufficient_evidence".
- Do NOT fabricate order flow, options data, or premarket context. Use only supplied facts.
```

Card record:
```json
{
  "role": "astra_llm_critic",
  "as_of": "<Z>",
  "claim": "reject|size_down|observe|approve|insufficient_evidence|missing",
  "facts": {
    "confidence": "low|medium|high|null",
    "rationale": "<one sentence>",
    "audit_id": "<sha>",
    "model_id": "astra-1.0",
    "status": "ok|not_configured|budget_exceeded|timeout|..."
  },
  "evidence_hash": "<sha>"
}
```

**Policy gate change** in `policy_gate`:
- If Astra card status is `ok` AND recommendation is `reject` → append blocker `astra_veto`.
- All other Astra states (approve, size_down, observe, insufficient_evidence, missing, budget_exceeded, timeout, not_configured) do NOT add or remove blockers.
- Astra approval never removes an existing blocker.

**Test** additions to `agent/tests/test_governed_shadow_decision.py`:
- Astra reject + deterministic pass → shadow_rejected with `astra_veto` blocker.
- Astra approve + deterministic reject → shadow_rejected, no change.
- Astra missing/timeout/budget_exceeded → no impact on decision, card emits `claim: "missing"`.
- Astra fabricated fact detection: if response contains keys outside the required schema → treated as `insufficient_evidence`.

---

## Workstream 13 — Astra attribution explainer (on top of WS6)

**Problem**: WS6 attribution rules are deterministic and coarse (`late_delivery`, `gap_through`, etc). Astra can produce a richer causal narrative for each alert.

**Extend** `scripts/alert_attribution_ledger.py`:

After deterministic attribution is written, call Astra for each row with prompt:

```
Given this alert's full lifecycle, produce a structured explanation.
Respond as strict JSON with keys: primary_driver, secondary_drivers, counterfactual, confidence.

primary_driver ∈ {deterministic reason list from WS6, plus "regime_shift", "correlated_move", "news_catalyst_reaction"}
counterfactual: one sentence describing what would have changed the outcome
confidence ∈ {"low", "medium", "high"}

Alert lifecycle (deterministic facts only, no interpretation):
{full attribution row minus the attribution.* keys}

Rules:
- Do NOT invent facts not in the lifecycle payload.
- Do NOT reference news headlines or external data.
- If the deterministic attribution already fully explains the outcome, echo it as primary_driver.
```

Append `astra_attribution` sub-object to attribution row:
```json
"astra_attribution": {
  "primary_driver": "...",
  "secondary_drivers": [...],
  "counterfactual": "...",
  "confidence": "...",
  "audit_id": "<sha>",
  "status": "ok|missing|..."
}
```

**Explicit forbidden**: Astra's `primary_driver` never overrides the deterministic `won_because` / `lost_because`. They coexist. Downstream nomination logic (WS7, WS9) reads only the deterministic fields for now — Astra fields are visibility only until A/B (WS15) proves signal.

**Test** `agent/tests/test_astra_attribution_explainer.py`:
- Astra ok → sub-object populated, deterministic fields unchanged.
- Astra missing → deterministic attribution still complete.
- Astra hallucinated fact (present in response but not in payload) → sub-object marked `status: "hallucination_detected"`, primary_driver dropped.

Hallucination detection: run a token-level check that every named entity in Astra's response is either (a) in the lifecycle payload as text, or (b) in the whitelist `{regime_shift, correlated_move, news_catalyst_reaction}` plus the WS6 deterministic list.

---

## Workstream 14 — Astra premarket thesis generator (extends WS3)

**Extend** `scripts/premarket_thesis_shadow.py`:

After deterministic premarket signal generation (NBBO flow, skew, gap-and-hold detection), call Astra with prompt:

```
You are a premarket bias generator. Given today's premarket facts, propose a
directional thesis for SPY, QQQ, IWM independently.

Respond as strict JSON: {symbol: {direction, conviction, evidence_summary, expires_at_et}}
direction ∈ {"LONG", "SHORT", "NO_BIAS"}
conviction ∈ {"low", "medium", "high"}
expires_at_et: HH:MM 24-hour ET, no later than 10:30 ET

Premarket facts (only source of truth):
- gap_percentage: {gap_pct}
- premarket_volume_ratio: {pm_vol_ratio}
- overnight_futures_move: {es_nq_rty_moves}
- options_nbbo_snapshot: {nbbo_facts}
- unusual_premium_prints: {prints}
- vix_open: {vix}
- economic_calendar_next_60min: {events}

Rules:
- Do NOT reference news, tweets, earnings, or macro events not in the payload.
- If NBBO or gap data is missing/stale, all three symbols must be NO_BIAS.
- If unusual_premium_prints array is empty, conviction max is "medium".
- Every thesis must include an evidence_summary that quotes numbers from the payload verbatim.
```

Emit thesis card only when Astra status is `ok` AND at least one facts field is populated AND `evidence_summary` contains at least one numeric token from the payload. Otherwise `status: "missing"`.

**Discord routing**: premarket theses go as `[PREMARKET THESIS · ASTRA]` OBSERVE-only, no SIMULATE. Existing deterministic premarket signals route separately as `[PREMARKET THESIS · DETERMINISTIC]`. Both routes labeled.

**Test** `agent/tests/test_astra_premarket_thesis.py`:
- Empty NBBO → all NO_BIAS.
- Empty unusual prints → conviction capped at medium.
- Response missing numeric evidence → status: fabricated, card dropped.
- Response references external headline → status: hallucination_detected, card dropped.

---

## Workstream 15 — A/B evaluation harness (edge proof)

**Problem**: Astra costs money and adds latency. Must prove edge before granting more roles.

**Implement** `scripts/astra_ab_evaluator.py`:

For each alert in `alert_attribution_ledger.jsonl` with an Astra card:
- Compute outcome R with Astra veto respected (real path).
- Compute counterfactual outcome R with Astra veto *ignored* (baseline path — as if Astra card was `missing`).
- Compute counterfactual outcome R with Astra veto *only* (Astra-alone path — as if deterministic gate was silent, Astra decides).

Bucket by regime (from WS6 regime_bucket). Require `MIN_SAMPLE=30` per bucket per role.

Report `~/.vibe-trading/reports/astra-ab-evaluation.json`:
```json
{
  "provider": "astra_ab_evaluator",
  "generated_at": "<Z>",
  "sessions_reviewed": 30,
  "by_role": {
    "critic_veto": {
      "sample_size": 47,
      "baseline_median_r": -0.30,
      "astra_augmented_median_r": -0.05,
      "astra_alone_median_r": -0.55,
      "baseline_hit_rate": 0.458,
      "astra_augmented_hit_rate": 0.512,
      "astra_alone_hit_rate": 0.400,
      "cost_usd_total": 3.42,
      "cost_usd_per_prevented_loss": 0.94,
      "verdict": "edge_positive|edge_negative|inconclusive"
    },
    "attribution_explainer": {...},
    "premarket_thesis": {...}
  },
  "promotion_recommendation": {
    "critic_veto": "keep|disable|expand_to_size_down_signal",
    "attribution_explainer": "keep|disable",
    "premarket_thesis": "keep|disable"
  },
  "policy": "human_review_required; no automatic role toggling",
  "execution_enabled": false,
  "can_submit_orders": false
}
```

Verdict rules:
- `edge_positive`: augmented median_r > baseline median_r by ≥0.15 AND augmented hit_rate ≥ baseline hit_rate AND `cost_usd_per_prevented_loss` < half of average loss size.
- `edge_negative`: augmented worse than baseline on both metrics.
- `inconclusive`: sample < MIN_SAMPLE per bucket OR mixed results.

Nightly runner step. Dashboard panel "Astra Edge Scorecard".

**Test** `agent/tests/test_astra_ab_evaluator.py`:
- Synthetic 47 rows with Astra preventing 5 losses at $0.50 each → edge_positive.
- Synthetic Astra always vetoing winners → edge_negative.
- Synthetic 20 rows → inconclusive.

---

## Workstream 16 — Astra prompt-response replay (reproducibility)

**Problem**: Vendor models update silently. Yesterday's prompt may return a different answer today. Need deterministic replay for regression tests.

**Implement** `scripts/astra_replay.py`:

Reads `astra_call_ledger.jsonl` and stores frozen prompt/response pairs in `data/astra_replay_fixtures.jsonl`. On replay, `astra_client.call(...)` in test mode returns the fixture instead of calling the API.

Rebuild attribution/decision/premarket pipelines against replay fixtures to verify a nightly re-run reproduces yesterday's outputs bit-for-bit *given identical prompts*.

If nightly replay produces different outputs — e.g., Astra silently upgraded — the report `~/.vibe-trading/reports/astra-replay-diff.json` flags it. Trigger: pause any promotion-in-progress until human reviews the drift.

**Test** `agent/tests/test_astra_replay.py`:
- Replay of identical prompt → identical output.
- Ledger row with truncated response → replay marks `status: "incomplete_fixture"`.
- Detected drift → replay diff report populated.

---

## Runner integration

Add to `scripts/run_intraday_opportunity_radar.ps1` in this order (after existing governed spine steps):

```
STEP astra_client_healthcheck        (dry-run: verify credentials + budget headroom, no billable call)
STEP astra_evidence_card_run          (called inline via governed_shadow_decision when present)
STEP astra_attribution_explainer      (after alert_attribution_ledger)
STEP astra_premarket_thesis           (premarket-only cadence, before 09:25 ET)
```

Add nightly (after 16:15 ET) `scripts/run_nightly_learning.ps1`:

```
STEP astra_ab_evaluator
STEP astra_replay_diff
```

Every step must survive Astra outage: check exit code, log, continue. Never let Astra failure abort the deterministic pipeline.

---

## Required checks

```powershell
python -m py_compile scripts/astra_client.py scripts/governed_shadow_decision.py scripts/alert_attribution_ledger.py scripts/premarket_thesis_shadow.py scripts/astra_ab_evaluator.py scripts/astra_replay.py
python -m pytest agent/tests/ -q -k "astra or governed_shadow_decision or premarket_thesis or attribution"
python scripts/order_authority_invariant.py
git diff --check
```

## Deliverable back to Claude

Report with:
- Files touched (path:line)
- Test counts
- Sample Astra critic card (ok, missing, budget_exceeded, hallucination_detected — one of each)
- Sample A/B verdict per role
- Cost ledger sample (5 rows)
- Replay drift report status
- Invariant status (must be violations=0)
- Confirmation that `execution_enabled` is nowhere `true`

---

## What Astra is NOT allowed to do

- Decide entries or exits
- Size trades
- Route alerts (routing stays deterministic based on grade + regime)
- Mutate any threshold, constant, config, or rule file
- Approve a candidate that the deterministic gate rejected
- Access broker APIs, order APIs, or credentials
- Read outside the alert-lifecycle payload
- Reference news, tweets, headlines, or macro events not supplied
- Self-evaluate its own edge (A/B is deterministic, run without Astra in the loop)

## What Astra IS allowed to do

- Add an extra blocker when it recommends `reject`
- Explain outcomes (WS13) as visibility-only
- Propose premarket theses (WS14) as OBSERVE-only Discord alerts, clearly labeled `ASTRA`
- Nominate itself for expanded roles via A/B evidence (WS15) — human decides

---

## Promotion criteria for expanded Astra roles

Astra critic role earns expansion only when A/B (WS15) shows:
- `edge_positive` verdict maintained across ≥3 consecutive weekly reports
- No hallucination-detected events in that window
- Cost/prevented-loss ratio ≤ 0.5
- Replay drift diffs reviewed and accepted
- Human reviewer signs `docs/PROMOTIONS_APPROVED.md`

Until then Astra stays exactly as speced: sixth critic card + attribution sidecar + premarket OBSERVE.

## Skepticism baked in

Astra is a vendor model with vendor-authored performance claims. Every architectural decision in this handoff assumes it will underperform, hallucinate, drift, and cost money. If it delivers edge anyway, the A/B harness will prove it and expand the role. If it doesn't, the deterministic spine is untouched and losses are capped at the daily budget.

Exponential accuracy is not a property of the model. It is a property of the loop that filters truth from vendor claims. This handoff builds the loop.
