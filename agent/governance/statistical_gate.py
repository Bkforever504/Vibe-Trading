"""Fail-closed statistical promotion gate for registered signal families."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np
import pandas as pd
from purgedcv import (CombinatorialPurgedCV, deflated_sharpe_ratio,
                      probabilistic_sharpe_ratio,
                      probability_of_backtest_overfitting)

from agent.governance.trial_ledger import DEFAULT_LEDGER, count_trials
from agent.analytics.outcome_bootstrap import (bootstrap_ci, mean_expectancy,
                                                sharpe as bootstrap_sharpe, win_rate)

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "research" / "signal_registry.json"
GATE_HISTORY = ROOT / "data" / "governance" / "gate_history"
PROMOTED_STATUSES = frozenset({"execution_capable_paper"})


@dataclass(frozen=True)
class GateDecision:
    signal_id: str
    family_key: str | None
    status: str
    n_outcomes: int
    n_trials: int | None
    sharpe: float | None
    deflated_sharpe: float | None
    psr: float | None
    pbo: float | None
    block_size: int | None
    iterations: int
    cpcv_folds: int
    embargo_bars: int
    model_version: str
    library_versions: dict[str, str]
    library_version_hash: str
    confidence_intervals: dict[str, dict[str, Any]]
    reason: str
    evaluated_at: str
    requires_human_review: bool
    registry_promotion_unchanged: bool
    execution_enabled: bool = False
    can_submit_orders: bool = False

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.update({"n": self.n_outcomes, "t": self.n_trials,
                      "b": self.block_size, "k": self.iterations})
        return value


def _model_version() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]


def _libraries() -> tuple[dict[str, str], str]:
    values = {name: version(name) for name in ("purgedcv", "numpy", "pandas")}
    digest = hashlib.sha256(repr(sorted(values.items())).encode()).hexdigest()[:12]
    return values, digest


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [value for line in path.read_text(encoding="utf-8-sig").splitlines()
            if line.strip() and isinstance((value := json.loads(line)), dict)]


def _normalized_return(row: Mapping[str, Any]) -> float | None:
    for key in ("outcome_r", "net_r", "return_pct", "pnl_pct", "realized_return_pct"):
        try:
            value = float(row.get(key))
            if math.isfinite(value):
                return value
        except (TypeError, ValueError):
            pass
    try:
        pnl = float(row.get("pnl"))
    except (TypeError, ValueError):
        return None
    risk = row.get("max_loss") or row.get("max_risk")
    if risk is None and row.get("max_risk_per_contract") is not None:
        risk = float(row["max_risk_per_contract"]) * max(1, int(row.get("qty") or 1))
    try:
        denominator = abs(float(risk))
        return pnl / denominator if denominator > 0 and math.isfinite(pnl) else None
    except (TypeError, ValueError):
        return pnl if math.isfinite(pnl) else None


def _path_rows(path: Path) -> list[dict[str, Any]]:
    value = _json(path) if path.suffix.lower() == ".json" else _jsonl(path)
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        for key in ("trades", "outcomes", "rows", "events"):
            if isinstance(value.get(key), list):
                return [row for row in value[key] if isinstance(row, dict)]
    return []


def _resolve_log_path(raw: str) -> Path | None:
    if not raw:
        return None
    expanded = Path(raw.replace("~", str(Path.home()), 1)) if raw.startswith("~") else Path(raw)
    return expanded if expanded.is_absolute() else ROOT / expanded


def default_outcome_loader(signal: Mapping[str, Any]) -> list[float]:
    path = _resolve_log_path(str(signal.get("log_path") or ""))
    if path is None or not path.exists():
        return []
    try:
        rows = _path_rows(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    start = str(signal.get("post_config_start_date") or "")[:10]
    if start:
        def observed_day(row: Mapping[str, Any]) -> str:
            for key in ("exit_date", "closed_at", "resolved_at", "date", "timestamp", "entry_date"):
                if row.get(key):
                    return str(row[key])[:10]
            return ""
        rows = [row for row in rows if observed_day(row) and observed_day(row) >= start]
    terminal = [row for row in rows if str(row.get("status") or "").lower() in
                {"closed", "resolved", "target", "stop", "expired", "invalidated"}]
    selected = terminal or rows
    return [value for row in selected if (value := _normalized_return(row)) is not None]


def sharpe_ratio(returns: np.ndarray) -> float:
    std = float(np.std(returns, ddof=1)) if len(returns) > 1 else 0.0
    return float(np.mean(returns) / std) if std > 0 else 0.0


def cpcv_audit(n: int) -> dict[str, Any]:
    if n < 8:
        return {"folds": 0, "leakage": None, "splits": []}
    groups = min(6, max(4, n // 5))
    test_groups = 2
    times = pd.Series(pd.date_range("2000-01-01", periods=n, freq="min"))
    evaluation = times + pd.Timedelta(minutes=1)
    cv = CombinatorialPurgedCV(groups, test_groups, prediction_times=times,
                               evaluation_times=evaluation, embargo_observations=1)
    audits = []
    for train, test in cv.split(np.zeros((n, 1))):
        overlap = bool(set(train).intersection(test))
        embargo_violation = any(index in set(train) for test_index in test for index in (test_index + 1,) if index < n)
        audits.append({"train_n": len(train), "test_n": len(test),
                       "overlap": overlap, "embargo_violation": embargo_violation})
    return {"folds": len(audits), "leakage": any(row["overlap"] or row["embargo_violation"] for row in audits),
            "splits": audits}


def deflated_sharpe_score(returns: np.ndarray, n_trials: int, trial_sharpes: list[float]) -> float | None:
    if n_trials < 1:
        return None
    variance = float(np.var(trial_sharpes, ddof=1)) if len(trial_sharpes) > 1 else 0.0
    if n_trials > 1 and len(trial_sharpes) < 2:
        return None
    return float(deflated_sharpe_ratio(returns, n_trials, variance))


def pbo_score(matrix: np.ndarray) -> float | None:
    if matrix.ndim != 2 or matrix.shape[0] < 2 or matrix.shape[1] < 8:
        return None
    splits = min(16, matrix.shape[1])
    if splits % 2:
        splits -= 1
    if splits < 4:
        return None
    return float(probability_of_backtest_overfitting(matrix, n_splits=splits).pbo)


class StatisticalGate:
    def __init__(self, *, registry_path: Path = REGISTRY_PATH, ledger_path: Path = DEFAULT_LEDGER,
                 outcome_loader: Callable[[Mapping[str, Any]], list[float]] = default_outcome_loader):
        self.registry_path = registry_path
        self.ledger_path = ledger_path
        self.outcome_loader = outcome_loader

    def _registry(self) -> dict[str, Any]:
        value = _json(self.registry_path)
        if not isinstance(value, dict) or not isinstance(value.get("signals"), list):
            raise ValueError("signal registry is invalid")
        return value

    def evaluate(self, signal_id: str) -> GateDecision:
        evaluated = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        libraries, library_hash = _libraries()
        base = {"signal_id": signal_id, "block_size": None, "iterations": 1000,
                "cpcv_folds": 0, "embargo_bars": 1, "model_version": _model_version(),
                "library_versions": libraries, "library_version_hash": library_hash,
                "evaluated_at": evaluated, "requires_human_review": True,
                "registry_promotion_unchanged": True, "confidence_intervals": {}}
        try:
            registry = self._registry()
            signal = next(row for row in registry["signals"] if row.get("id") == signal_id)
        except (OSError, ValueError, StopIteration, json.JSONDecodeError) as exc:
            return GateDecision(**base, family_key=None, status="error", n_outcomes=0, n_trials=None,
                                sharpe=None, deflated_sharpe=None, psr=None, pbo=None,
                                reason=f"registry_unavailable:{type(exc).__name__}")
        family = str(signal.get("family_key") or "") or None
        returns = np.asarray(self.outcome_loader(signal), dtype=float)
        returns = returns[np.isfinite(returns)]
        confidence = {
            "expectancy": bootstrap_ci(returns, mean_expectancy),
            "win_rate": bootstrap_ci(returns, win_rate),
            "sharpe": bootstrap_ci(returns, bootstrap_sharpe),
        }
        base["confidence_intervals"] = confidence
        base["block_size"] = confidence["sharpe"].get("block_size")
        gate = signal.get("promotion_gate") if isinstance(signal.get("promotion_gate"), Mapping) else {}
        minimum = int(gate.get("min_outcomes") or 30)
        try:
            trials = count_trials(str(family), path=self.ledger_path) if family else None
        except (OSError, ValueError, json.JSONDecodeError):
            trials = None
        if trials is None or trials < 1:
            return GateDecision(**base, family_key=family, status="error", n_outcomes=len(returns), n_trials=trials,
                                sharpe=None, deflated_sharpe=None, psr=None, pbo=None,
                                reason="trial_ledger_missing_or_family_unrecorded")
        if len(returns) < minimum:
            status = "needs_review" if signal.get("status") in PROMOTED_STATUSES else "not_ready"
            return GateDecision(**base, family_key=family, status=status, n_outcomes=len(returns), n_trials=trials,
                                sharpe=None, deflated_sharpe=None, psr=None, pbo=None,
                                reason=f"insufficient_outcomes:{len(returns)}/{minimum}")
        audit = cpcv_audit(len(returns))
        raw_sharpe = sharpe_ratio(returns)
        psr = float(probabilistic_sharpe_ratio(returns, 0.0))
        family_signals = [row for row in registry["signals"] if row.get("family_key") == family]
        family_returns = [np.asarray(self.outcome_loader(row), dtype=float) for row in family_signals]
        family_returns = [row[np.isfinite(row)] for row in family_returns if len(row) >= 8]
        trial_sharpes = [sharpe_ratio(row) for row in family_returns]
        dsr = deflated_sharpe_score(returns, trials, trial_sharpes)
        shortest = min((len(row) for row in family_returns), default=0)
        matrix = np.vstack([row[-shortest:] for row in family_returns]) if shortest else np.empty((0, 0))
        pbo = pbo_score(matrix)
        if audit["leakage"] or dsr is None or pbo is None:
            reason = "cpcv_leakage_detected" if audit["leakage"] else "family_trial_returns_insufficient_for_dsr_pbo"
            status = "needs_review" if signal.get("status") in PROMOTED_STATUSES else "not_ready"
        else:
            min_dsr = gate.get("min_deflated_sharpe")
            min_psr = float(gate.get("min_psr") if gate.get("min_psr") is not None else .95)
            max_pbo = float(gate.get("max_pbo") if gate.get("max_pbo") is not None else .5)
            passed = (min_dsr is None or dsr >= float(min_dsr)) and psr >= min_psr and pbo <= max_pbo
            status = "ready_for_human_review" if passed else "needs_review"
            reason = "statistical_thresholds_passed_human_review_required" if passed else "statistical_threshold_failed"
        return GateDecision(**{**base, "cpcv_folds": audit["folds"]}, family_key=family, status=status,
                            n_outcomes=len(returns), n_trials=trials, sharpe=raw_sharpe,
                            deflated_sharpe=dsr, psr=psr, pbo=pbo, reason=reason)


def append_gate_history(decision: GateDecision, *, directory: Path = GATE_HISTORY) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{decision.signal_id}.jsonl"
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(decision.to_dict(), sort_keys=True, separators=(",", ":")) + "\n")
    return target
