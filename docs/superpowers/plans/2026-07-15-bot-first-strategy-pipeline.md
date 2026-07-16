# Bot-First Strategy Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a research-only CLI that turns sufficiently explicit plain-English strategy descriptions into immutable packets, validates adapters and evidence assumptions, writes reproducible run cards, bridges completed research to the immutable trial ledger, and links the existing 30-minute Strat shadow strategy.

**Architecture:** Keep strategy interpretation, adapter safety, artifact persistence, and trial registration in separate focused modules. The CLI composes these authorities but has no broker imports or live command. Packet validation fails closed on ambiguous risk, exit, data, or holdout rules; adapter execution is allowed only after AST validation and only for registered research adapters.

**Tech Stack:** Python 3.12, standard-library dataclasses/AST/hashlib/json/argparse/pathlib, existing pandas research stack, pytest, existing `scripts/edge_trial_ledger.py`.

---

## File Map

- Create `research/strategy_pipeline.py`: canonical packet schema, hashing, validation, atomic packet persistence.
- Create `research/strategy_language.py`: constrained plain-English/labeled-clause interpretation and ambiguity reporting.
- Create `research/strategy_adapter_safety.py`: AST allow/deny validator for research adapters.
- Create `research/strategy_run_cards.py`: immutable run-card identity and atomic artifact writes.
- Create `research/strategy_trial_bridge.py`: conversion of completed run cards into ledger records.
- Create `scripts/strategy_pipeline.py`: `intake`, `validate`, `run`, `show`, and `list` CLI.
- Create `research/strategy_packets/strat_30m_continuation_v1.json`: first canonical linked packet.
- Create `research/strategy_platform_intake_2026-07-15.md`: keep/reject report for external platforms and repositories.
- Create `agent/tests/test_strategy_pipeline.py`: schema, language, CLI, and Strat-link tests.
- Create `agent/tests/test_strategy_adapter_safety.py`: adapter security tests.
- Create `agent/tests/test_strategy_run_cards.py`: artifact and ledger-bridge tests.

### Task 1: Canonical Strategy Packet

**Files:**
- Create: `research/strategy_pipeline.py`
- Test: `agent/tests/test_strategy_pipeline.py`

- [ ] **Step 1: Write failing canonicalization and validation tests**

```python
from research.strategy_pipeline import packet_id, validate_packet


def _packet():
    return {
        "schema_version": 1,
        "name": "SPY 30m continuation",
        "thesis": "Enter after a confirmed first-30-minute range break.",
        "market": {"asset_class": "equity_options", "symbols": ["SPY"], "timeframe": "1m", "timezone": "America/New_York"},
        "rules": {
            "setup": "completed 30-minute opening range",
            "entry": "close above opening-range high",
            "stop": "opening-range low",
            "targets": ["2R"],
            "exit": "stop, target, or 15:45 ET",
            "sizing": "fixed paper unit",
            "session": "09:30-15:45 ET",
        },
        "data": {"bars": ["1m", "1d"], "point_in_time_required": True},
        "research": {"dataset_start": "2025-01-01", "dataset_end": "2025-12-31", "oos_start": "2025-10-01", "oos_end": "2025-12-31", "benchmark": "SPY", "cost_model": "options_quote_mid_plus_half_spread"},
        "provenance": {"original_prompt": "explicit test prompt", "source": "test"},
        "authority": {"mode": "research_only", "execution_enabled": False, "can_submit_orders": False, "promotion_requires_human_approval": True},
    }


def test_packet_id_is_stable_and_ignores_runtime_metadata():
    left = _packet()
    right = {**_packet(), "created_at": "2026-07-15T18:00:00Z"}
    assert packet_id(left) == packet_id(right)


def test_rule_change_creates_new_packet_id():
    changed = _packet()
    changed["rules"]["targets"] = ["3R"]
    assert packet_id(_packet()) != packet_id(changed)


def test_missing_stop_fails_closed():
    packet = _packet()
    packet["rules"]["stop"] = ""
    result = validate_packet(packet)
    assert result.valid is False
    assert "missing_rules.stop" in result.errors
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `python -m pytest agent/tests/test_strategy_pipeline.py -q`

Expected: FAIL because `research.strategy_pipeline` does not exist.

- [ ] **Step 3: Implement the minimal immutable packet contract**

Implement `ValidationResult`, `canonical_packet`, `packet_id`, `validate_packet`, and `write_packet_atomic`. Canonical identity must omit only runtime fields (`created_at`, `updated_at`, `status`, `last_run_id`) and include every trading rule, data requirement, research window, and authority field. Validation must require all schema sections, reject reversed dates, and enforce the four exact authority values from the test fixture.

```python
@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...] = ()


def packet_id(packet: dict[str, Any]) -> str:
    payload = json.dumps(canonical_packet(packet), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]
```

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m pytest agent/tests/test_strategy_pipeline.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the packet contract**

```text
git add research/strategy_pipeline.py agent/tests/test_strategy_pipeline.py
git commit -m "feat: add canonical research strategy packets"
```

### Task 2: Constrained Plain-English Intake

**Files:**
- Create: `research/strategy_language.py`
- Modify: `agent/tests/test_strategy_pipeline.py`

- [ ] **Step 1: Write failing interpretation tests**

```python
from research.strategy_language import interpret_description


def test_explicit_labeled_description_builds_complete_rules():
    result = interpret_description(
        "symbol: SPY; timeframe: 1m; setup: first 30 minute range complete; "
        "entry: close above range high; stop: range low; target: 2R; "
        "exit: stop, target, or 15:45 ET; sizing: fixed paper unit; session: 09:30-15:45 ET"
    )
    assert result.status == "ready_for_validation"
    assert result.fields["symbols"] == ["SPY"]
    assert result.fields["rules"]["target"] == "2R"


def test_unlabeled_promo_language_never_invents_risk_rules():
    result = interpret_description("Buy SPY calls when it looks ready to explode.")
    assert result.status == "needs_rules"
    assert "stop" in result.missing_fields
    assert "exit" in result.missing_fields
    assert result.fields.get("stop") is None
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m pytest agent/tests/test_strategy_pipeline.py -q`

Expected: FAIL because `research.strategy_language` does not exist.

- [ ] **Step 3: Implement deterministic clause parsing**

Split semicolon-delimited `key: value` clauses and support only these keys: `symbol`, `symbols`, `timeframe`, `setup`, `entry`, `stop`, `target`, `targets`, `exit`, `sizing`, `session`, `benchmark`, `dataset`, `oos`, and `cost_model`. Normalize symbols to uppercase and preserve all rule text verbatim. Unknown clauses become ambiguities; missing material fields produce `needs_rules`. Do not call an LLM inside this module.

```python
MATERIAL_FIELDS = ("symbols", "timeframe", "setup", "entry", "stop", "target", "exit", "sizing", "session")

@dataclass(frozen=True)
class Interpretation:
    status: str
    fields: dict[str, Any]
    missing_fields: tuple[str, ...]
    ambiguities: tuple[str, ...]
```

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m pytest agent/tests/test_strategy_pipeline.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the language boundary**

```text
git add research/strategy_language.py agent/tests/test_strategy_pipeline.py
git commit -m "feat: add fail-closed strategy language intake"
```

### Task 3: Research Adapter Safety Validator

**Files:**
- Create: `research/strategy_adapter_safety.py`
- Create: `agent/tests/test_strategy_adapter_safety.py`

- [ ] **Step 1: Write failing allowed/denied AST tests**

```python
from research.strategy_adapter_safety import validate_adapter_source


def test_pandas_signal_adapter_is_allowed():
    source = "import pandas as pd\n\ndef strategy(frame):\n    return pd.Series(0, index=frame.index)\n"
    result = validate_adapter_source(source)
    assert result.safe is True


def test_broker_network_and_process_imports_are_blocked():
    for module in ("alpaca", "requests", "socket", "subprocess"):
        result = validate_adapter_source(f"import {module}\n")
        assert result.safe is False
        assert any(module in error for error in result.errors)


def test_dynamic_execution_is_blocked():
    for expression in ("eval('1+1')", "exec('x=1')", "__import__('os')"):
        assert validate_adapter_source(expression).safe is False
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest agent/tests/test_strategy_adapter_safety.py -q`

Expected: FAIL because the validator module does not exist.

- [ ] **Step 3: Implement AST validation**

Allow imports from `math`, `statistics`, `numpy`, `pandas`, and approved local research modules. Reject broker SDKs, network/process/file-mutation modules, dynamic import/evaluation calls, and any function or attribute containing `submit_order`, `place_order`, `cancel_order`, `replace_order`, or `close_position`. Return all violations in deterministic sorted order.

```python
@dataclass(frozen=True)
class AdapterSafetyResult:
    safe: bool
    errors: tuple[str, ...]
```

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m pytest agent/tests/test_strategy_adapter_safety.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the safety validator**

```text
git add research/strategy_adapter_safety.py agent/tests/test_strategy_adapter_safety.py
git commit -m "feat: validate research strategy adapters"
```

### Task 4: Immutable Run Cards

**Files:**
- Create: `research/strategy_run_cards.py`
- Create: `agent/tests/test_strategy_run_cards.py`

- [ ] **Step 1: Write failing run-card tests**

```python
from research.strategy_run_cards import build_run_card, write_run_card


def test_run_card_is_research_only_and_reproducible(tmp_path):
    card = build_run_card(packet_id="abc123", packet={"name": "test"}, validation={"valid": True}, metrics=None)
    assert card["execution_enabled"] is False
    assert card["can_submit_orders"] is False
    assert card["status"] == "validated_not_backtested"
    first = write_run_card(card, tmp_path)
    second = write_run_card(card, tmp_path)
    assert first == second
    assert first.read_bytes() == second.read_bytes()
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest agent/tests/test_strategy_run_cards.py -q`

Expected: FAIL because the run-card module does not exist.

- [ ] **Step 3: Implement run cards and atomic writes**

Build a `run_id` from packet ID, code version, dataset provenance, cost model, and metrics payload. Use `tempfile.NamedTemporaryFile` in the destination directory followed by `os.replace`. Refuse to overwrite an existing run ID with different bytes. Metrics absent means `validated_not_backtested`; metrics present means `research_complete` only when required metrics and provenance are complete.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m pytest agent/tests/test_strategy_run_cards.py -q`

Expected: PASS.

- [ ] **Step 5: Commit run cards**

```text
git add research/strategy_run_cards.py agent/tests/test_strategy_run_cards.py
git commit -m "feat: add reproducible strategy run cards"
```

### Task 5: Honest Edge-Trial Ledger Bridge

**Files:**
- Create: `research/strategy_trial_bridge.py`
- Modify: `agent/tests/test_strategy_run_cards.py`

- [ ] **Step 1: Write failing bridge tests**

```python
import pytest
from research.strategy_trial_bridge import ledger_trial_from_run_card


def test_validation_only_card_cannot_enter_trial_ledger():
    with pytest.raises(ValueError, match="completed research metrics required"):
        ledger_trial_from_run_card({"status": "validated_not_backtested", "metrics": None})


def test_completed_card_maps_oos_metrics_without_promotion():
    card = {
        "status": "research_complete",
        "packet_id": "abc",
        "packet": {"name": "test", "thesis": "test edge", "research": {"dataset_start": "2025-01-01", "dataset_end": "2025-12-31", "oos_start": "2025-10-01", "oos_end": "2025-12-31", "cost_model": "half_spread"}},
        "metrics": {"oos_trade_count": 40, "oos_expectancy": 0.02, "oos_profit_factor": 1.3, "oos_max_drawdown": 0.12},
        "code_version": "deadbeef",
    }
    trial = ledger_trial_from_run_card(card)
    assert trial["stage"] == "out_of_sample"
    assert trial["execution_enabled"] is False
    assert trial["can_submit_orders"] is False
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest agent/tests/test_strategy_run_cards.py -q`

Expected: FAIL because the bridge module does not exist.

- [ ] **Step 3: Implement the bridge**

Map only `research_complete` cards with dataset provenance, cost model, and non-empty metrics. Call `scripts.edge_trial_ledger.validate_trial` before returning. Do not call `record_trial` from the converter; the CLI performs the explicit append so tests can use temporary ledgers.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m pytest agent/tests/test_strategy_run_cards.py agent/tests/test_edge_trial_ledger.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the bridge**

```text
git add research/strategy_trial_bridge.py agent/tests/test_strategy_run_cards.py
git commit -m "feat: bridge completed strategy research to trial ledger"
```

### Task 6: Research-Only CLI

**Files:**
- Create: `scripts/strategy_pipeline.py`
- Modify: `agent/tests/test_strategy_pipeline.py`

- [ ] **Step 1: Write failing CLI tests**

```python
import json
import subprocess
import sys


def test_cli_has_no_live_or_execute_command():
    result = subprocess.run([sys.executable, "scripts/strategy_pipeline.py", "--help"], capture_output=True, text=True, check=True)
    assert "intake" in result.stdout
    assert "validate" in result.stdout
    assert "run" in result.stdout
    assert " live" not in result.stdout.lower()
    assert "execute" not in result.stdout.lower()


def test_cli_intake_writes_needs_rules_packet(tmp_path):
    result = subprocess.run(
        [sys.executable, "scripts/strategy_pipeline.py", "intake", "--describe", "Buy SPY calls when ready", "--name", "draft", "--out-dir", str(tmp_path)],
        capture_output=True, text=True, check=False,
    )
    payload = json.loads(result.stdout)
    assert result.returncode == 2
    assert payload["status"] == "needs_rules"
    assert payload["execution_enabled"] is False
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest agent/tests/test_strategy_pipeline.py -q`

Expected: FAIL because the CLI does not exist.

- [ ] **Step 3: Implement CLI orchestration**

Implement subcommands:

- `intake`: interpret labeled clauses, build a draft packet, validate, and atomically persist it.
- `validate`: validate packet plus optional adapter source; write a validation run card.
- `run`: require an approved registered adapter and explicit dataset/metrics artifact. Never infer or fabricate metrics. Write the run card and append a ledger trial only for `research_complete`.
- `show`: print one run card by ID.
- `list`: print packet/run summaries filtered by status.

All commands emit JSON by default; `--print` is accepted as an explicit compatibility alias for scheduled-report conventions already used in the repository.

All command outputs include `execution_enabled: false` and `can_submit_orders: false`. Exit codes: `0` success, `2` needs rules/validation failure, `3` unsafe adapter, `4` incomplete evidence.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python -m pytest agent/tests/test_strategy_pipeline.py agent/tests/test_strategy_adapter_safety.py agent/tests/test_strategy_run_cards.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the CLI**

```text
git add scripts/strategy_pipeline.py agent/tests/test_strategy_pipeline.py
git commit -m "feat: add research-only strategy pipeline CLI"
```

### Task 7: Link the Existing 30-Minute Strat Strategy

**Files:**
- Create: `research/strategy_packets/strat_30m_continuation_v1.json`
- Modify: `agent/tests/test_strategy_pipeline.py`

- [ ] **Step 1: Write the failing linkage test**

```python
import json
from pathlib import Path

from research.strategy_pipeline import validate_packet


def test_strat_packet_links_existing_shadow_implementation():
    packet = json.loads(Path("research/strategy_packets/strat_30m_continuation_v1.json").read_text())
    assert validate_packet(packet).valid is True
    assert packet["adapter"]["module"] == "strategies.strat_30m_continuation"
    assert packet["adapter"]["callable"] == "evaluate_strat_30m"
    assert packet["monitor"]["script"] == "scripts/strat_30m_continuation_shadow.py"
    assert packet["authority"]["mode"] == "research_only"
```

- [ ] **Step 2: Run the test and verify RED**

Run: `python -m pytest agent/tests/test_strategy_pipeline.py::test_strat_packet_links_existing_shadow_implementation -q`

Expected: FAIL because the packet does not exist.

- [ ] **Step 3: Add the canonical linked packet**

Encode the current implemented behavior exactly: daily outside-bar context, full-timeframe continuity, completed first 30-minute range, rebreak trigger after 10:00 ET, shadow call direction, prior-week/whole-dollar context, current no-live authority, required daily and minute bars, current monitor script, and a research contract that marks option-level historical backtest metrics unavailable until point-in-time option quotes are supplied. Do not claim a completed historical trial.

- [ ] **Step 4: Validate the packet and existing strategy tests**

Run: `python -m pytest agent/tests/test_strategy_pipeline.py agent/tests/test_strat_30m_continuation.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the first linked strategy**

```text
git add research/strategy_packets/strat_30m_continuation_v1.json agent/tests/test_strategy_pipeline.py
git commit -m "feat: link Strat continuation to strategy pipeline"
```

### Task 8: External Platform Intake Report

**Files:**
- Create: `research/strategy_platform_intake_2026-07-15.md`

- [ ] **Step 1: Write the report with explicit decisions**

Document each reviewed source with `adopt`, `evaluate`, or `reject`:

- Adopt: reproducible run cards, editable structured strategies, deterministic static validation, scenario monitoring, benchmark comparisons, point-in-time cost-aware research.
- Evaluate later: LEAN adapter, isolated generated-code subprocess, trace UI, persistent research memory with retention controls.
- Reject: proprietary signal copying, social-media return claims, automatic live deployment, LLM self-scoring, repeated parameter search without immutable trial counting.

Include direct links to TrendSpider, Capitalise.ai, Composer, QuantConnect, HKUDS/Vibe-Trading, VibeTradingLabs/vibetrading, LEAN, and QSTrader. Record that the last30days run had X and YouTube failures and did not produce evidence of profitability.

- [ ] **Step 2: Commit the research report**

```text
git add research/strategy_platform_intake_2026-07-15.md
git commit -m "docs: evaluate strategy builder platform patterns"
```

- [ ] **Step 3: Verify no external runtime dependency was added**

Run: `git diff --name-only HEAD~1..HEAD` and confirm only `research/strategy_platform_intake_2026-07-15.md` changed in that commit.

### Task 9: Final Verification and Safety Audit

**Files:**
- Modify only if verification reveals a defect in files created by Tasks 1-8.

- [ ] **Step 1: Run focused tests**

Run:

```text
python -m pytest agent/tests/test_strategy_pipeline.py agent/tests/test_strategy_adapter_safety.py agent/tests/test_strategy_run_cards.py agent/tests/test_edge_trial_ledger.py agent/tests/test_strat_30m_continuation.py -q
```

Expected: all pass.

- [ ] **Step 2: Compile all new Python modules**

Run:

```text
python -m py_compile research/strategy_pipeline.py research/strategy_language.py research/strategy_adapter_safety.py research/strategy_run_cards.py research/strategy_trial_bridge.py scripts/strategy_pipeline.py
```

Expected: exit code 0 and no output.

- [ ] **Step 3: Audit execution authority**

Run:

```text
rg -n "submit_order|place_order|cancel_order|replace_order|close_position|execution_enabled|can_submit_orders" research/strategy_*.py scripts/strategy_pipeline.py research/strategy_packets/strat_30m_continuation_v1.json
```

Expected: order method names appear only in deny lists/tests; every artifact path fixes both execution flags to false.

- [ ] **Step 4: Exercise the CLI**

Run:

```text
python scripts/strategy_pipeline.py validate --packet research/strategy_packets/strat_30m_continuation_v1.json --print
```

Expected: valid linked packet, research-only authority, no ledger append, and no order activity.

- [ ] **Step 5: Confirm unrelated worktree changes remain untouched**

Run: `git status --short`

Expected: pre-existing modified and untracked files remain; only strategy-pipeline files belong to this implementation.

- [ ] **Step 6: Commit any verification-only corrections**

If a correction was required, stage only the strategy-pipeline files and use:

```text
git commit -m "fix: harden strategy pipeline verification"
```
