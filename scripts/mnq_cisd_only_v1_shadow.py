"""Thin runtime adapter for the frozen MNQ CISD-only ablation."""
from scripts.mnq_smt_family_shadow import STRATEGY_CONFIGS, run_entry as _entry, run_resolve as _resolve

CONFIG = STRATEGY_CONFIGS["mnq-cisd-only-v1"]
STRATEGY_ID = CONFIG.strategy_id
SPEC_HASH = CONFIG.spec_hash
LOG_PATH = CONFIG.log_path
execution_enabled = False
can_submit_orders = False


def run_entry(*, log_path=LOG_PATH, as_of=None):
    return _entry(CONFIG, log_path=log_path, as_of=as_of)


def run_resolve(*, log_path=LOG_PATH, as_of=None):
    return _resolve(CONFIG, log_path=log_path, as_of=as_of)
