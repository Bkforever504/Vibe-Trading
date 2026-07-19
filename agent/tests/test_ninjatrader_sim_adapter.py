from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from unittest.mock import patch

from strategies.ninjatrader_sim_adapter import (
    ALLOWED_ATM_STRATEGY,
    EXECUTION_CONFIRMATION,
    LOCAL_DEVICE_CONFIRMATION,
    NinjaTraderSafetyError,
    NinjaTraderSimAdapter,
    NinjaTraderSimConfig,
    build_close_position_oif,
    build_place_oif,
)


def root(tmp_path: Path, *, atm: bool = True) -> Path:
    ninja = tmp_path / "NinjaTrader 8"
    (ninja / "incoming").mkdir(parents=True)
    (ninja / "outgoing").mkdir()
    (ninja / "Config.xml").write_text(
        "<NinjaTrader><IsAtiEnabled>true</IsAtiEnabled></NinjaTrader>", encoding="utf-8"
    )
    if atm:
        template = ninja / "templates" / "AtmStrategy" / f"{ALLOWED_ATM_STRATEGY}.xml"
        template.parent.mkdir(parents=True)
        template.write_text(
            "<NinjaTrader><AtmStrategy><EntryQuantity>1</EntryQuantity>"
            "<CalculationMode>Ticks</CalculationMode><Brackets><Bracket>"
            "<Quantity>1</Quantity><StopLoss>40</StopLoss><Target>80</Target>"
            "</Bracket></Brackets></AtmStrategy></NinjaTrader>",
            encoding="utf-8",
        )
    return ninja


def config(tmp_path: Path, *, atm: bool = True) -> NinjaTraderSimConfig:
    ninja = root(tmp_path, atm=atm)
    log_dir = ninja / "log"
    log_dir.mkdir()
    (log_dir / "log.20260720.00000.txt").write_text(
        "Automated trading enabled\nSimulation: Primary connection=Connected, Price feed=Connected\n",
        encoding="utf-8",
    )
    return NinjaTraderSimConfig(
        ninja_root=ninja,
        execution_confirmation=EXECUTION_CONFIRMATION,
        local_device_confirmation=LOCAL_DEVICE_CONFIRMATION,
        journal_path=tmp_path / "journal.jsonl",
        block_file=tmp_path / "manual-reset.json",
    )


def monday_10am_et() -> datetime:
    return datetime(2026, 7, 20, 14, 0, tzinfo=timezone.utc)


def test_place_command_is_locked_to_sim101_one_mes_and_atm() -> None:
    command = build_place_oif(
        side="buy", instrument="MES 09-26", order_id="OID", strategy_id="SID",
        atm_strategy=ALLOWED_ATM_STRATEGY,
    )
    assert command == "PLACE;Sim101;MES 09-26;BUY;1;MARKET;;;DAY;;OID;VibeMES40x80;SID"
    assert len(command.split(";")) == 13


def test_close_command_is_scoped_to_sim101_mes() -> None:
    command = build_close_position_oif(instrument="MES 09-26")
    assert command.startswith("CLOSEPOSITION;Sim101;MES 09-26;")
    assert len(command.split(";")) == 13


def test_readiness_is_non_trading_and_reports_missing_template(tmp_path: Path) -> None:
    adapter = NinjaTraderSimAdapter(config=config(tmp_path, atm=False))
    status = adapter.readiness()
    assert status["ati_enabled"] is True
    assert status["atm_template_exists"] is False
    assert status["atm_template_verified"] is False
    assert list((adapter.config.incoming_dir).iterdir()) == []


def test_entry_dispatches_unique_oif_and_journals_without_claiming_fill(tmp_path: Path) -> None:
    cfg = config(tmp_path)
    adapter = NinjaTraderSimAdapter(config=cfg, now_fn=monday_10am_et)
    with patch("strategies.ninjatrader_sim_adapter._ninjatrader_process_running", return_value=True):
        result = adapter.place_mes_entry(side="sell")
    assert result["status"] == "oif_dispatched"
    files = list(cfg.incoming_dir.glob("oif-entry-*.txt"))
    assert len(files) == 1
    command = files[0].read_text(encoding="ascii").strip()
    assert command.startswith("PLACE;Sim101;MES 09-26;SELL;1;MARKET")
    rows = [json.loads(line) for line in cfg.journal_path.read_text().splitlines()]
    assert [row["status"] for row in rows] == ["submitting", "oif_dispatched"]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda cfg: NinjaTraderSimConfig(**{**cfg.__dict__, "execution_confirmation": ""}), "confirmation"),
        (lambda cfg: NinjaTraderSimConfig(**{**cfg.__dict__, "instrument": "MNQ 09-26"}), "MES"),
        (lambda cfg: NinjaTraderSimConfig(**{**cfg.__dict__, "atm_strategy": "Other"}), "allowlisted"),
    ],
)
def test_entry_fails_closed_before_writing_oif(tmp_path: Path, mutate, message: str) -> None:
    cfg = mutate(config(tmp_path))
    adapter = NinjaTraderSimAdapter(config=cfg, now_fn=monday_10am_et)
    with patch("strategies.ninjatrader_sim_adapter._ninjatrader_process_running", return_value=True):
        with pytest.raises(NinjaTraderSafetyError, match=message):
            adapter.place_mes_entry(side="buy")
    assert list(cfg.incoming_dir.iterdir()) == []


def test_missing_atm_and_kill_switch_block_entry(tmp_path: Path) -> None:
    cfg = config(tmp_path, atm=False)
    adapter = NinjaTraderSimAdapter(config=cfg, now_fn=monday_10am_et)
    with patch("strategies.ninjatrader_sim_adapter._ninjatrader_process_running", return_value=True):
        with pytest.raises(NinjaTraderSafetyError, match="ATM"):
            adapter.place_mes_entry(side="buy")
        cfg.block_file.write_text("{}", encoding="utf-8")
        with pytest.raises(NinjaTraderSafetyError, match="kill switch"):
            adapter.place_mes_entry(side="buy")


def test_one_entry_per_session_and_outside_window_are_blocked(tmp_path: Path) -> None:
    cfg = config(tmp_path)
    adapter = NinjaTraderSimAdapter(config=cfg, now_fn=monday_10am_et)
    with patch("strategies.ninjatrader_sim_adapter._ninjatrader_process_running", return_value=True):
        adapter.place_mes_entry(side="buy")
        with pytest.raises(NinjaTraderSafetyError, match="already exists"):
            adapter.place_mes_entry(side="buy")
    late = NinjaTraderSimAdapter(
        config=NinjaTraderSimConfig(**{**cfg.__dict__, "journal_path": tmp_path / "late.jsonl"}),
        now_fn=lambda: datetime(2026, 7, 20, 17, 0, tzinfo=timezone.utc),
    )
    with patch("strategies.ninjatrader_sim_adapter._ninjatrader_process_running", return_value=True):
        with pytest.raises(NinjaTraderSafetyError, match="outside"):
            late.place_mes_entry(side="buy")


def test_emergency_close_works_through_kill_switch_but_stays_sim_mes(tmp_path: Path) -> None:
    cfg = config(tmp_path)
    cfg.block_file.write_text("{}", encoding="utf-8")
    adapter = NinjaTraderSimAdapter(config=cfg, now_fn=monday_10am_et)
    with patch("strategies.ninjatrader_sim_adapter._ninjatrader_process_running", return_value=True):
        result = adapter.emergency_close_mes()
    command = Path(result["oif_path"]).read_text(encoding="ascii")
    assert "CLOSEPOSITION;Sim101;MES 09-26" in command


def test_order_state_parser(tmp_path: Path) -> None:
    cfg = config(tmp_path)
    (cfg.outgoing_dir / "OID.txt").write_text("Filled;1;6412.25", encoding="utf-8")
    state = NinjaTraderSimAdapter(config=cfg).order_state("OID")
    assert state and state["order_state"] == "Filled"
    assert state["filled"] == 1
    assert state["average_fill_price"] == 6412.25
