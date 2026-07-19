#!/usr/bin/env python3
"""Fail-closed NinjaTrader OIF adapter for local Sim101 MES practice.

This module deliberately cannot target a live account. Entries also require a
pre-existing NinjaTrader ATM strategy so every fill receives its protective
stop and target from NinjaTrader itself.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strategies.topstepx_practice_adapter import to_eastern


SIM_ACCOUNT = "Sim101"
EXECUTION_CONFIRMATION = "SIM101_ONLY_CONFIRMED"
LOCAL_DEVICE_CONFIRMATION = "PERSONAL_DEVICE_CONFIRMED"
ALLOWED_ATM_STRATEGY = "VibeMES40x80"
EXPECTED_STOP_TICKS = 40
EXPECTED_TARGET_TICKS = 80
MES_INSTRUMENT_PATTERN = re.compile(r"^MES \d{2}-\d{2}$")
DEFAULT_JOURNAL = Path.home() / ".vibe-trading" / "ninjatrader-sim-oif-journal.jsonl"
DEFAULT_BLOCK_FILE = Path.home() / ".vibe-trading" / "MANUAL_RESET_REQUIRED.json"


class NinjaTraderSafetyError(RuntimeError):
    """A simulation-only invariant failed."""


def discover_ninjatrader_root() -> Path:
    candidates = (
        Path.home() / "OneDrive" / "Documents" / "NinjaTrader 8",
        Path.home() / "Documents" / "NinjaTrader 8",
    )
    matches = [path for path in candidates if path.is_dir()]
    if len(matches) != 1:
        raise NinjaTraderSafetyError(
            f"Expected exactly one NinjaTrader 8 data directory, found {len(matches)}"
        )
    return matches[0]


@dataclass(frozen=True)
class NinjaTraderSimConfig:
    ninja_root: Path
    instrument: str = "MES 09-26"
    atm_strategy: str = ALLOWED_ATM_STRATEGY
    max_contracts: int = 1
    entry_start_et: time = time(9, 45)
    entry_cutoff_et: time = time(12, 15)
    execution_confirmation: str = ""
    local_device_confirmation: str = ""
    journal_path: Path = DEFAULT_JOURNAL
    block_file: Path = DEFAULT_BLOCK_FILE

    @classmethod
    def from_env(cls, *, ninja_root: Path | None = None) -> "NinjaTraderSimConfig":
        return cls(
            ninja_root=ninja_root or discover_ninjatrader_root(),
            instrument=os.environ.get("NINJATRADER_MES_CONTRACT", "MES 09-26").strip(),
            execution_confirmation=os.environ.get("NINJATRADER_SIM_EXECUTION", "").strip(),
            local_device_confirmation=os.environ.get("NINJATRADER_LOCAL_DEVICE", "").strip(),
        )

    @property
    def incoming_dir(self) -> Path:
        return self.ninja_root / "incoming"

    @property
    def outgoing_dir(self) -> Path:
        return self.ninja_root / "outgoing"

    @property
    def atm_template_path(self) -> Path:
        return self.ninja_root / "templates" / "AtmStrategy" / f"{self.atm_strategy}.xml"


def _append_journal(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def _journal_has_entry(path: Path, session_date: str) -> bool:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return False
    blocking = {"submitting", "unknown", "oif_dispatched", "working", "filled"}
    latest: dict[str, str] = {}
    for index, line in enumerate(lines):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("session_date") != session_date:
            continue
        order_id = str(row.get("order_id") or f"legacy-{index}")
        latest[order_id] = str(row.get("status") or "")
    return any(status in blocking for status in latest.values())


def _ati_enabled(config_path: Path) -> bool:
    try:
        root = ET.parse(config_path).getroot()
    except (OSError, ET.ParseError):
        return False
    node = root.find(".//IsAtiEnabled")
    return node is not None and (node.text or "").strip().lower() == "true"


def _protective_atm_matches(path: Path) -> bool:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return False
    quantity = root.findtext(".//Bracket/Quantity")
    stop = root.findtext(".//Bracket/StopLoss")
    target = root.findtext(".//Bracket/Target")
    mode = root.findtext(".//CalculationMode")
    entry_quantity = root.findtext(".//EntryQuantity")
    return (
        quantity == "1"
        and entry_quantity == "1"
        and stop == str(EXPECTED_STOP_TICKS)
        and target == str(EXPECTED_TARGET_TICKS)
        and mode == "Ticks"
    )


def _ninjatrader_process_running() -> bool:
    if os.name != "nt":
        return False
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq NinjaTrader.exe", "/NH"],
        capture_output=True,
        text=True,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return "NinjaTrader.exe" in result.stdout


def _runtime_log_status(log_dir: Path) -> tuple[bool, bool]:
    logs = sorted(log_dir.glob("log.*.txt"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not logs:
        return False, False
    try:
        text = logs[0].read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return False, False
    automated = "Automated trading enabled" in text
    connection_lines = [line for line in text.splitlines() if "Simulation: Primary connection=" in line]
    connected = bool(connection_lines and "Primary connection=Connected" in connection_lines[-1])
    return automated, connected


def build_place_oif(
    *, side: str, instrument: str, order_id: str, strategy_id: str, atm_strategy: str
) -> str:
    action = {"buy": "BUY", "sell": "SELL"}.get(side)
    if action is None:
        raise ValueError("side must be buy or sell")
    fields = [
        "PLACE", SIM_ACCOUNT, instrument, action, "1", "MARKET", "", "", "DAY", "",
        order_id, atm_strategy, strategy_id,
    ]
    return ";".join(fields)


def build_close_position_oif(*, instrument: str) -> str:
    return ";".join(["CLOSEPOSITION", SIM_ACCOUNT, instrument] + [""] * 10)


class NinjaTraderSimAdapter:
    def __init__(
        self,
        *,
        config: NinjaTraderSimConfig | None = None,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config or NinjaTraderSimConfig.from_env()
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    def readiness(self) -> dict[str, Any]:
        config_path = self.config.ninja_root / "Config.xml"
        automated, connected = _runtime_log_status(self.config.ninja_root / "log")
        return {
            "mode": "ninjatrader_sim101_only",
            "account": SIM_ACCOUNT,
            "instrument": self.config.instrument,
            "ninja_root": str(self.config.ninja_root),
            "ati_enabled": _ati_enabled(config_path),
            "incoming_exists": self.config.incoming_dir.is_dir(),
            "outgoing_exists": self.config.outgoing_dir.is_dir(),
            "atm_strategy": self.config.atm_strategy,
            "atm_template_exists": self.config.atm_template_path.is_file(),
            "atm_template_verified": _protective_atm_matches(self.config.atm_template_path),
            "execution_confirmed": self.config.execution_confirmation == EXECUTION_CONFIRMATION,
            "local_device_confirmed": self.config.local_device_confirmation == LOCAL_DEVICE_CONFIRMATION,
            "kill_switch_active": self.config.block_file.exists(),
            "ninjatrader_process_running": _ninjatrader_process_running(),
            "automated_trading_runtime_enabled": automated,
            "simulation_connected": connected,
        }

    def _assert_base_safety(self, *, risk_reducing: bool = False) -> None:
        if self.config.execution_confirmation != EXECUTION_CONFIRMATION:
            raise NinjaTraderSafetyError("Sim101 execution confirmation is missing")
        if self.config.local_device_confirmation != LOCAL_DEVICE_CONFIRMATION:
            raise NinjaTraderSafetyError("Personal-device confirmation is missing")
        if not MES_INSTRUMENT_PATTERN.fullmatch(self.config.instrument):
            raise NinjaTraderSafetyError("Instrument must be an explicit MES contract")
        if not _ati_enabled(self.config.ninja_root / "Config.xml"):
            raise NinjaTraderSafetyError("NinjaTrader AT Interface is not enabled")
        if not self.config.incoming_dir.is_dir():
            raise NinjaTraderSafetyError("NinjaTrader incoming directory is missing")
        if not _ninjatrader_process_running():
            raise NinjaTraderSafetyError("NinjaTrader Desktop is not running")
        automated, connected = _runtime_log_status(self.config.ninja_root / "log")
        if not automated or not connected:
            raise NinjaTraderSafetyError("NinjaTrader simulation runtime is not connected with ATI enabled")
        if self.config.block_file.exists() and not risk_reducing:
            raise NinjaTraderSafetyError("Global manual-reset kill switch is active")

    def _dispatch(self, command: str, *, order_id: str, kind: str, session_date: str) -> Path:
        self.config.incoming_dir.mkdir(parents=True, exist_ok=True)
        staging = self.config.ninja_root / "tmp" / "vibe-trading-oif"
        staging.mkdir(parents=True, exist_ok=True)
        filename = f"oif-{kind}-{order_id}-{uuid4().hex[:8]}.txt"
        source = staging / filename
        target = self.config.incoming_dir / filename
        source.write_text(command + "\n", encoding="ascii", newline="\n")
        try:
            os.replace(source, target)
        except OSError:
            _append_journal(self.config.journal_path, {
                "recorded_at": self.now_fn().isoformat(), "session_date": session_date,
                "order_id": order_id, "status": "unknown", "kind": kind,
            })
            raise
        return target

    def place_mes_entry(self, *, side: str, size: int = 1) -> dict[str, Any]:
        self._assert_base_safety()
        now = to_eastern(self.now_fn())
        local_time = now.time().replace(tzinfo=None)
        if not self.config.entry_start_et <= local_time <= self.config.entry_cutoff_et:
            raise NinjaTraderSafetyError("Entry is outside the 09:45-12:15 ET simulation window")
        if side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        if size != 1 or size > self.config.max_contracts:
            raise NinjaTraderSafetyError("Simulation entry must be exactly one MES contract")
        if self.config.atm_strategy != ALLOWED_ATM_STRATEGY:
            raise NinjaTraderSafetyError("ATM strategy is not allowlisted")
        if not _protective_atm_matches(self.config.atm_template_path):
            raise NinjaTraderSafetyError("Protective ATM strategy template is missing or does not match 1x40/80 ticks")

        session_date = now.date().isoformat()
        if _journal_has_entry(self.config.journal_path, session_date):
            raise NinjaTraderSafetyError("One simulation entry already exists for this session")

        order_id = f"VIBE-MES-{now:%Y%m%d}-{uuid4().hex[:10]}"
        strategy_id = f"VIBE-ATM-{now:%Y%m%d}-{uuid4().hex[:10]}"
        command = build_place_oif(
            side=side,
            instrument=self.config.instrument,
            order_id=order_id,
            strategy_id=strategy_id,
            atm_strategy=self.config.atm_strategy,
        )
        base = {
            "recorded_at": now.isoformat(),
            "session_date": session_date,
            "order_id": order_id,
            "strategy_id": strategy_id,
            "status": "submitting",
            "mode": "ninjatrader_sim101_only",
            "account": SIM_ACCOUNT,
            "instrument": self.config.instrument,
            "side": side,
            "size": 1,
            "atm_strategy": self.config.atm_strategy,
        }
        _append_journal(self.config.journal_path, base)
        target = self._dispatch(command, order_id=order_id, kind="entry", session_date=session_date)
        result = {**base, "status": "oif_dispatched", "oif_path": str(target)}
        _append_journal(self.config.journal_path, result)
        return result

    def emergency_close_mes(self) -> dict[str, Any]:
        """Request cancellation of MES orders and flatten MES on Sim101 only."""
        self._assert_base_safety(risk_reducing=True)
        now = to_eastern(self.now_fn())
        order_id = f"VIBE-CLOSE-{now:%Y%m%d}-{uuid4().hex[:10]}"
        session_date = now.date().isoformat()
        command = build_close_position_oif(instrument=self.config.instrument)
        target = self._dispatch(command, order_id=order_id, kind="close", session_date=session_date)
        result = {
            "recorded_at": now.isoformat(), "session_date": session_date,
            "order_id": order_id, "status": "close_oif_dispatched",
            "mode": "ninjatrader_sim101_only", "account": SIM_ACCOUNT,
            "instrument": self.config.instrument, "oif_path": str(target),
        }
        _append_journal(self.config.journal_path, result)
        return result

    def order_state(self, order_id: str) -> dict[str, Any] | None:
        path = self.config.outgoing_dir / f"{order_id}.txt"
        try:
            raw = path.read_text(encoding="utf-8-sig").strip()
        except OSError:
            return None
        parts = [part.strip() for part in raw.split(";")]
        if len(parts) < 3:
            raise NinjaTraderSafetyError("Malformed NinjaTrader order-state file")
        try:
            filled = int(parts[1])
            average_fill_price = float(parts[2])
        except ValueError as exc:
            raise NinjaTraderSafetyError("Malformed NinjaTrader order-state values") from exc
        return {
            "order_id": order_id,
            "order_state": parts[0],
            "filled": filled,
            "average_fill_price": average_fill_price,
            "source": str(path),
        }


if __name__ == "__main__":
    print(json.dumps(NinjaTraderSimAdapter().readiness(), indent=2, sort_keys=True))
