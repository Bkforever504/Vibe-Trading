#!/usr/bin/env python3
"""Register the frozen MNQ SMT/CISD ablation family for shadow research.

The command is append-only and retry-safe. It validates the entire four-spec
pack and immutable universe before touching either ledger, then advances each
candidate through proposed -> development -> shadow. It has no broker or order
authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from scripts.hypothesis_ledger import (
        EXPERIMENT_FAMILY_PATH,
        HYPOTHESIS_LEDGER_PATH,
        append_hypothesis_event,
        experiment_family_size,
        latest_hypotheses,
        read_jsonl,
        record_frozen_spec,
    )
    from scripts.preregistration_validator import validate_spec
except ImportError:
    from hypothesis_ledger import (  # type: ignore
        EXPERIMENT_FAMILY_PATH,
        HYPOTHESIS_LEDGER_PATH,
        append_hypothesis_event,
        experiment_family_size,
        latest_hypotheses,
        read_jsonl,
        record_frozen_spec,
    )
    from preregistration_validator import validate_spec  # type: ignore


ROOT = Path(__file__).resolve().parent.parent
FAMILY_ID = "mnq-smt-cisd-family"
UNIVERSE_PATH = ROOT / "data" / "universes" / "mnq_smt_family_2026-08-24.json"
EXPECTED_UNIVERSE = {
    "universe_id": "cme-mnq-smt-family",
    "universe_version": "cme-mnq-nq-mes-es-front-month-roll8-v1",
    "universe_hash": "sha256:84d8ceaebd9f55d346059aba4809f8389fbe26099cd7878b0498c12dcd11ddbe",
    "membership_as_of": "2026-08-24",
}
CANDIDATES: tuple[dict[str, Any], ...] = (
    {
        "candidate_id": "mnq-smt-cisd-fvg-v1",
        "spec_path": "research/preregistrations/mnq_smt_cisd_fvg_v1.md",
        "spec_hash": "sha256:686aed721b83bc2e0c0051adc2af863f2eeee459874c8f13d275489c56b7bb2d",
        "origin": "social",
        "blockers": (
            "databento_mbo_required",
            "executable_futures_bbo_required",
            "kenny_signoff_required",
            "out_of_sample_holdout_pass_required",
        ),
    },
    {
        "candidate_id": "mnq-pdl-rejection-v1",
        "spec_path": "research/preregistrations/mnq_pdl_rejection_v1.md",
        "spec_hash": "sha256:54cb3221c4fabdc9d04cf85ca9dcdf3f041883fab230feb113936969ca3732ba",
        "origin": "research",
        "blockers": (
            "databento_mbo_required",
            "executable_futures_bbo_required",
            "kenny_signoff_required",
        ),
    },
    {
        "candidate_id": "mnq-smt-only-v1",
        "spec_path": "research/preregistrations/mnq_smt_only_v1.md",
        "spec_hash": "sha256:b2680f71689b392dda80a1ffd5a1a5bac4453edee8e1e4e5801a01d6fca12bd0",
        "origin": "research",
        "blockers": (
            "databento_mbo_required",
            "executable_futures_bbo_required",
            "kenny_signoff_required",
        ),
    },
    {
        "candidate_id": "mnq-cisd-only-v1",
        "spec_path": "research/preregistrations/mnq_cisd_only_v1.md",
        "spec_hash": "sha256:b55a94d9663662eb59d18a6eb23af8808ac752bb015fb676005d716680719b4a",
        "origin": "research",
        "blockers": (
            "databento_mbo_required",
            "executable_futures_bbo_required",
            "kenny_signoff_required",
        ),
    },
)
SPEC_PATHS = tuple(ROOT / candidate["spec_path"] for candidate in CANDIDATES)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_membership_hash(symbols: Iterable[str]) -> str:
    canonical = "".join(f"{symbol}\n" for symbol in sorted(set(symbols)))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_universe(path: Path) -> dict[str, str]:
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid_mnq_family_universe:{exc}") from exc
    symbols = document.get("symbols")
    if not isinstance(symbols, list) or not symbols or any(not isinstance(value, str) for value in symbols):
        raise ValueError("invalid_mnq_family_universe:symbols")
    normalized = [value.strip().upper() for value in symbols]
    if normalized != sorted(set(normalized)):
        raise ValueError("universe_symbols_must_be_sorted_unique_uppercase")
    if document.get("symbol_count") != len(normalized):
        raise ValueError("universe_symbol_count_mismatch")
    declared_hash = str(document.get("sha256_membership_hash") or "")
    if _canonical_membership_hash(normalized) != declared_hash:
        raise ValueError("universe_membership_hash_mismatch")
    actual_identity = {
        "universe_id": str(document.get("universe_id") or ""),
        "universe_version": str(document.get("universe_version") or ""),
        "universe_hash": declared_hash,
        "membership_as_of": str(document.get("membership_as_of") or ""),
    }
    if actual_identity != EXPECTED_UNIVERSE:
        raise ValueError("unexpected_mnq_family_universe_identity")
    return actual_identity


def _validate_specs(spec_paths: Iterable[Path], universe: dict[str, str]) -> dict[str, dict[str, Any]]:
    expected = {candidate["candidate_id"]: candidate for candidate in CANDIDATES}
    validated: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    for path in spec_paths:
        result = validate_spec(path)
        metadata = result.get("metadata") or {}
        candidate_id = str(metadata.get("Spec ID") or path.stem)
        candidate = expected.get(candidate_id)
        errors = list(result.get("errors") or [])
        if candidate is None:
            errors.append("unexpected_spec_id")
        else:
            comparisons = {
                "Family ID": FAMILY_ID,
                "Origin": candidate["origin"],
                "Spec Hash": candidate["spec_hash"],
                "Universe ID": universe["universe_id"],
                "Universe Version": universe["universe_version"],
                "Universe Hash": universe["universe_hash"],
                "Membership As Of": universe["membership_as_of"],
            }
            errors.extend(
                f"metadata_mismatch:{field}"
                for field, expected_value in comparisons.items()
                if metadata.get(field) != expected_value
            )
        if candidate_id in validated:
            errors.append("duplicate_spec_id")
        if errors:
            failures.append(f"{candidate_id}=" + ",".join(sorted(set(errors))))
        else:
            validated[candidate_id] = {"path": path, "validation": result, "candidate": candidate}
    missing = sorted(set(expected) - set(validated))
    if missing:
        failures.append("missing_spec_ids=" + ",".join(missing))
    if failures or len(validated) != len(CANDIDATES):
        raise ValueError("invalid_mnq_family_specs:" + ";".join(failures))
    return validated


def _check_existing_identity(
    *,
    hypothesis_path: Path,
    family_path: Path,
    universe: dict[str, str],
) -> None:
    expected = {candidate["candidate_id"]: candidate for candidate in CANDIDATES}
    family_rows = read_jsonl(family_path)
    for row in family_rows:
        candidate_id = str(row.get("candidate_id") or "")
        if row.get("family_id") == FAMILY_ID and candidate_id not in expected:
            raise ValueError(f"unexpected_candidate_in_family:{candidate_id}")
        if candidate_id in expected:
            candidate = expected[candidate_id]
            identity = {
                "family_id": FAMILY_ID,
                "spec_hash": candidate["spec_hash"],
                "spec_path": candidate["spec_path"],
                "origin": candidate["origin"],
                **universe,
            }
            if any(row.get(field) != value for field, value in identity.items()):
                raise ValueError(f"existing_family_identity_conflict:{candidate_id}")
    current = latest_hypotheses(hypothesis_path)
    for candidate_id, candidate in expected.items():
        row = current.get(candidate_id)
        if not row:
            continue
        identity = {
            "family_id": FAMILY_ID,
            "spec_hash": candidate["spec_hash"],
            "spec_path": candidate["spec_path"],
            "origin": candidate["origin"],
            **universe,
        }
        if any(row.get(field) != value for field, value in identity.items()):
            raise ValueError(f"existing_hypothesis_identity_conflict:{candidate_id}")
        if row.get("status") == "rejected":
            raise ValueError(f"rejected_candidate_cannot_reenter_shadow:{candidate_id}")


def _base_candidate(candidate: dict[str, Any], universe: dict[str, str]) -> dict[str, Any]:
    return {
        "id": candidate["candidate_id"],
        "spec_hash": candidate["spec_hash"],
        "spec_path": candidate["spec_path"],
        "family_id": FAMILY_ID,
        "origin": candidate["origin"],
        **universe,
        "n_resolved": 0,
        "distinct_sessions": 0,
        "first_resolved_at": None,
        "last_evaluated_at": None,
        "dsr": None,
        "dsr_lower_bound": None,
        "pbo": None,
        "expectancy_lb": None,
    }


def _register_validated(
    *,
    hypothesis_path: Path,
    family_path: Path,
    universe: dict[str, str],
) -> dict[str, Any]:
    proposed_added = 0
    development_added = 0
    shadow_added = 0
    family_added = 0
    results: list[dict[str, Any]] = []
    for candidate in CANDIDATES:
        base = _base_candidate(candidate, universe)
        current = latest_hypotheses(hypothesis_path).get(candidate["candidate_id"])
        transitions: list[str] = []
        if current is None:
            result = append_hypothesis_event(
                {**base, "status": "proposed", "verdict_reason": "frozen_spec_pending_intake_validation"},
                hypothesis_path,
                event_type="candidate_proposed",
            )
            proposed_added += int(result["recorded"])
            transitions.append("proposed")
            current = latest_hypotheses(hypothesis_path)[candidate["candidate_id"]]

        family_result = record_frozen_spec(
            candidate_id=candidate["candidate_id"],
            family_id=FAMILY_ID,
            spec_hash=candidate["spec_hash"],
            spec_path=candidate["spec_path"],
            origin=candidate["origin"],
            **universe,
            path=family_path,
        )
        family_added += int(family_result["recorded"])

        if current.get("status") == "proposed":
            result = append_hypothesis_event(
                {**base, "status": "development", "verdict_reason": "frozen_spec_validated"},
                hypothesis_path,
                event_type="preregistration_validated",
            )
            development_added += int(result["recorded"])
            transitions.append("development")
            current = latest_hypotheses(hypothesis_path)[candidate["candidate_id"]]

        if current.get("status") == "development":
            blocker_reason = "promotion_ineligible:blockers=" + ",".join(candidate["blockers"])
            result = append_hypothesis_event(
                {**base, "status": "shadow", "verdict_reason": blocker_reason},
                hypothesis_path,
                event_type="shadow_challenger_registered",
            )
            shadow_added += int(result["recorded"])
            transitions.append("shadow")
            current = latest_hypotheses(hypothesis_path)[candidate["candidate_id"]]

        results.append(
            {
                "candidate_id": candidate["candidate_id"],
                "spec_hash": candidate["spec_hash"],
                "origin": candidate["origin"],
                "status": current.get("status"),
                "transitions_added": transitions,
                "blockers": list(candidate["blockers"]),
                "execution_enabled": False,
                "can_submit_orders": False,
            }
        )
    family_size = experiment_family_size(family_path, FAMILY_ID)
    if family_size != len(CANDIDATES):
        raise RuntimeError(f"mnq_family_size_mismatch:{family_size}!={len(CANDIDATES)}")
    return {
        "provider": "register_mnq_smt_family",
        "schema_version": 1,
        "generated_at": _utc_now(),
        "mode": "shadow_research_governance",
        "valid_specs": len(CANDIDATES),
        "proposed_events_added": proposed_added,
        "development_events_added": development_added,
        "shadow_events_added": shadow_added,
        "family_specs_added": family_added,
        "family_id": FAMILY_ID,
        "family_size": family_size,
        "results": results,
        "execution_enabled": False,
        "can_submit_orders": False,
        "orders_submitted": 0,
    }


def register_family(
    *,
    spec_paths: Iterable[Path] = SPEC_PATHS,
    universe_path: Path = UNIVERSE_PATH,
    hypothesis_path: Path = HYPOTHESIS_LEDGER_PATH,
    family_path: Path = EXPERIMENT_FAMILY_PATH,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Validate and idempotently register the complete four-candidate family."""
    paths = tuple(Path(path) for path in spec_paths)
    universe = _validate_universe(Path(universe_path))
    _validate_specs(paths, universe)
    _check_existing_identity(
        hypothesis_path=Path(hypothesis_path),
        family_path=Path(family_path),
        universe=universe,
    )
    if dry_run:
        with tempfile.TemporaryDirectory(prefix="mnq-smt-family-") as temp_dir:
            temp_root = Path(temp_dir)
            temp_hypothesis = temp_root / "hypothesis.jsonl"
            temp_family = temp_root / "family.jsonl"
            if Path(hypothesis_path).exists():
                shutil.copy2(hypothesis_path, temp_hypothesis)
            if Path(family_path).exists():
                shutil.copy2(family_path, temp_family)
            report = _register_validated(
                hypothesis_path=temp_hypothesis,
                family_path=temp_family,
                universe=universe,
            )
        return {**report, "dry_run": True, "writes_performed": False}
    report = _register_validated(
        hypothesis_path=Path(hypothesis_path),
        family_path=Path(family_path),
        universe=universe,
    )
    writes_performed = any(
        report[field]
        for field in (
            "proposed_events_added",
            "development_events_added",
            "shadow_events_added",
            "family_specs_added",
        )
    )
    return {**report, "dry_run": False, "writes_performed": writes_performed}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", action="append", type=Path, default=[])
    parser.add_argument("--universe", type=Path, default=UNIVERSE_PATH)
    parser.add_argument("--hypothesis-ledger", type=Path, default=HYPOTHESIS_LEDGER_PATH)
    parser.add_argument("--family-ledger", type=Path, default=EXPERIMENT_FAMILY_PATH)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    report = register_family(
        spec_paths=args.spec or SPEC_PATHS,
        universe_path=args.universe,
        hypothesis_path=args.hypothesis_ledger,
        family_path=args.family_ledger,
        dry_run=args.dry_run,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
