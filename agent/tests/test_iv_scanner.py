from __future__ import annotations

import io
import sys
from types import SimpleNamespace

from scripts import ivr_scanner


def _snap(iv):
    return SimpleNamespace(implied_volatility=iv, greeks=None)


def test_select_atm_iv_uses_sorted_nearest_expiry_and_both_sides() -> None:
    snapshot = {
        "AAPL260918C00200000": _snap(0.90),
        "AAPL260814C00190000": _snap(0.40),
        "AAPL260814C00200000": _snap(0.30),
        "AAPL260814P00200000": _snap(0.34),
        "AAPL260814P00210000": _snap(0.50),
    }

    assert ivr_scanner._select_atm_iv(snapshot, "AAPL", 201.0) == 0.32


def test_select_atm_iv_accepts_valid_snapshot_without_greeks() -> None:
    snapshot = {"NVDA260814C00150000": _snap(0.45)}

    assert ivr_scanner._select_atm_iv(snapshot, "NVDA", 150.0) == 0.45


def test_select_atm_iv_ignores_invalid_values_and_symbols() -> None:
    snapshot = {
        "TSLA260814C00300000": _snap(None),
        "TSLA260814P00300000": _snap(-0.1),
        "not-an-occ-symbol": _snap(0.4),
    }

    assert ivr_scanner._select_atm_iv(snapshot, "TSLA", 300.0) is None


def test_atm_iv_method_is_versioned() -> None:
    assert {"SPY", "QQQ", "IWM", "AAPL", "NVDA", "TSLA", "PLTR"}.issubset(set(ivr_scanner.SYMBOLS))
    assert ivr_scanner.ATM_IV_DTE_MIN == 7
    assert ivr_scanner.ATM_IV_DTE_MAX == 45
    assert ivr_scanner.ATM_IV_METHOD.endswith("_v2")
    assert ivr_scanner.MIN_IVR_HISTORY == 30


def test_scan_keeps_chain_status_ok_while_ivr_history_accumulates(monkeypatch) -> None:
    monkeypatch.setattr(ivr_scanner, "_fetch_spot", lambda _symbol: 150.0)
    monkeypatch.setattr(ivr_scanner, "_fetch_atm_iv", lambda _symbol, _spot: 0.45)
    monkeypatch.setattr(ivr_scanner, "_load_iv_history", lambda _symbol: [])

    result = ivr_scanner.scan_symbol("NVDA")

    assert result["status"] == "ok"
    assert result["ivr_status"] == "accumulating"
    assert result["current_iv_pct"] == 45.0
    assert result["ivr"] is None


def test_iv_history_never_mixes_method_versions(tmp_path) -> None:
    log_path = tmp_path / "iv.jsonl"
    log_path.write_text(
        '{"date":"2026-08-01","scans":['
        '{"symbol":"AAPL","atm_iv":0.2},'
        '{"symbol":"AAPL","atm_iv":0.3,"atm_iv_method":"old_v1"},'
        '{"symbol":"AAPL","atm_iv":0.4,"atm_iv_method":"nearest_expiry_7_45d_mean_atm_call_put_v2"}'
        ']}\n',
        encoding="utf-8",
    )

    assert ivr_scanner._load_iv_history("AAPL", log_path) == [0.4]


def test_report_is_safe_for_windows_cp1252_console(monkeypatch) -> None:
    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", stream)

    ivr_scanner.print_report([{
        "symbol": "AAPL",
        "status": "ok",
        "spot": 200.0,
        "current_iv_pct": 30.0,
        "ivr": None,
        "history_days": 1,
        "note": "accumulating",
    }])
    stream.flush()


def test_true_ivr_requires_full_minimum_history() -> None:
    result = ivr_scanner.compute_ivr(0.4, [0.2 + index / 1000 for index in range(29)])

    assert result["status"] == "accumulating"
    assert result["ivr"] is None
