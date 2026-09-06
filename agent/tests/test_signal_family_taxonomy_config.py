import json
from pathlib import Path


TAXONOMY_PATH = Path(__file__).resolve().parents[2] / "config" / "signal_families.json"


def test_reactive_catalyst_and_alt_data_boundaries_are_mutually_exclusive() -> None:
    taxonomy = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    families = taxonomy["families"]

    reactive = families["catalyst_reactive"]["description"].lower()
    alt_data = families["alt_data_smart_money"]["description"].lower()

    assert "discrete, timestamped" in reactive
    assert "excludes rolling or longitudinal positioning aggregates" in reactive
    assert "rolling or longitudinal" in alt_data
    assert "excludes signals triggered directly by an individual edgar/sec filing" in alt_data


def test_taxonomy_examples_are_unique_across_families() -> None:
    taxonomy = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    owners: dict[str, str] = {}

    for family_key, definition in taxonomy["families"].items():
        for signal_id in definition["example_signals"]:
            assert signal_id not in owners, (
                f"{signal_id} appears in both {owners[signal_id]} and {family_key}"
            )
            owners[signal_id] = family_key
