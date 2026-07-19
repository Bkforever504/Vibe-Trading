#!/usr/bin/env python3
"""Record option-aware evidence for fixed liquid-underlying shadow setups.

No trading client is imported. The script can read bars and option snapshots,
then append evidence. It cannot submit, replace, or cancel an order.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.liquid_universe_orb_replication import Variant, fetch_bars, replay as replay_first_bar
from research.liquid_universe_retest_lab import RetestConfig, replay as replay_retest
from scripts.point_in_time_quotes import capture_lifecycle_sample
from strategies.flip_contract_ranker import rank_contracts

NY = ZoneInfo("America/New_York")
LOG_PATH = ROOT / "data" / "liquid_options_edge_shadow_log.jsonl"
REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "liquid-options-edge-shadow.json"
QUOTE_PATH = Path.home() / ".vibe-trading" / "logs" / "option-quote-samples.jsonl"

CANDIDATES = (
    {
        "symbol": "QQQ",
        "strategy": "or15_retest_ema_rvol_2r",
        "kind": "retest",
        "config": RetestConfig("or15_retest_ema_rvol_2r", 15, require_ema_fan=True, require_rvol=True),
        "evidence_status": "shadow_only_unstable_across_periods_and_costs",
    },
    {
        "symbol": "TQQQ",
        "strategy": "paper_first5m_direction_rvol",
        "kind": "first_bar",
        "config": Variant("paper_eod_rvol", "first_bar", None, True),
        "evidence_status": "shadow_only_short_side_regime_dependent",
    },
)


def select_contract(candidates: list[dict[str, Any]], direction: str) -> dict[str, Any] | None:
    wanted = "CALL" if direction == "long" else "PUT"
    eligible = [candidate for candidate in candidates if str(candidate.get("right", "")).upper() == wanted]
    ranked = rank_contracts(eligible)
    valid = [row for row in ranked if not row["contract_rank"]["disqualified"]]
    return valid[0] if valid else None


def fetch_contract_candidates(symbol: str, direction: str, *, min_dte: int = 7, max_dte: int = 14) -> list[dict[str, Any]]:
    """Read Alpaca indicative chain snapshots; never touches trading endpoints."""
    from alpaca.data.historical import OptionHistoricalDataClient
    from alpaca.data.requests import OptionChainRequest
    import scripts.market_data as market_data

    market_data._load_env()  # noqa: SLF001
    if not (market_data._ALPACA_KEY and market_data._ALPACA_SECRET):  # noqa: SLF001
        return []
    today = datetime.now(NY).date()
    right = "call" if direction == "long" else "put"
    request = OptionChainRequest(
        underlying_symbol=symbol,
        expiration_date_gte=today + timedelta(days=min_dte),
        expiration_date_lte=today + timedelta(days=max_dte),
        type=right,
    )
    client = OptionHistoricalDataClient(market_data._ALPACA_KEY, market_data._ALPACA_SECRET)  # noqa: SLF001
    snapshots = client.get_option_chain(request)
    rows: list[dict[str, Any]] = []
    for option_symbol, snapshot in snapshots.items():
        quote = getattr(snapshot, "latest_quote", None)
        greeks = getattr(snapshot, "greeks", None)
        if quote is None or greeks is None:
            continue
        bid = float(getattr(quote, "bid_price", 0.0) or 0.0)
        ask = float(getattr(quote, "ask_price", 0.0) or 0.0)
        if bid <= 0 or ask < bid:
            continue
        mid = (bid + ask) / 2.0
        delta = getattr(greeks, "delta", None)
        strike = int(option_symbol[len(symbol) + 7 :]) / 1000.0
        rows.append(
            {
                "option_symbol": option_symbol,
                "strike": strike,
                "right": "CALL" if right == "call" else "PUT",
                "delta": float(delta) if delta is not None else None,
                "spread_pct": round((ask - bid) / mid * 100.0, 3) if mid > 0 else None,
                "quote_age_seconds": None,
                "expected_move_room": None,
                "premium_expansion_pct": None,
                "bid": bid,
                "ask": ask,
                "quote_timestamp": str(getattr(quote, "timestamp", "") or "") or None,
            }
        )
    return rows


def latest_underlying_signal(candidate: dict[str, Any], trading_day: date) -> dict[str, Any] | None:
    start = (trading_day - timedelta(days=70)).isoformat()
    frame = fetch_bars(candidate["symbol"], start=start)
    if candidate["kind"] == "retest":
        trades = replay_retest(frame, candidate["config"], cost_bps_per_side=1.0)
    else:
        trades = replay_first_bar(frame, candidate["config"], cost_bps_per_side=1.0)
    matches = [trade for trade in trades if trade["date"] == trading_day.isoformat()]
    if not matches:
        return None
    trade = matches[-1]
    return {
        "symbol": candidate["symbol"],
        "strategy": candidate["strategy"],
        "direction": trade["direction"],
        "signal_time": trade.get("entry_time") or f"{trading_day.isoformat()}T09:35:00-04:00",
        "entry_reference": trade.get("entry"),
        "stop_reference": trade.get("stop"),
        "risk_bps": trade.get("risk_bps"),
        "rvol": trade.get("rvol"),
        "evidence_status": candidate["evidence_status"],
    }


def _existing_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    ids: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("signal_id"):
            ids.add(str(record["signal_id"]))
    return ids


def append_record(record: dict[str, Any], path: Path = LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def build_report(
    trading_day: date | None = None,
    *,
    signal_fetcher=latest_underlying_signal,
    contract_fetcher=fetch_contract_candidates,
    capture_quotes: bool = True,
    log_path: Path = LOG_PATH,
) -> dict[str, Any]:
    trading_day = trading_day or datetime.now(NY).date()
    report: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.now(NY).isoformat(),
        "date": trading_day.isoformat(),
        "mode": "shadow_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "signals": [],
        "blockers": [],
    }
    if trading_day.weekday() >= 5:
        report["status"] = "market_closed"
        return report
    existing = _existing_ids(log_path)
    for candidate in CANDIDATES:
        try:
            signal = signal_fetcher(candidate, trading_day)
        except Exception as exc:
            report["blockers"].append(f"{candidate['symbol']}:underlying_signal_error:{str(exc)[:120]}")
            continue
        if signal is None:
            continue
        signal_id = f"{signal['strategy']}:{signal['symbol']}:{signal['signal_time']}:{signal['direction']}"
        if signal_id in existing:
            continue
        try:
            contracts = contract_fetcher(signal["symbol"], signal["direction"])
            selected = select_contract(contracts, signal["direction"])
        except Exception as exc:
            selected = None
            report["blockers"].append(f"{signal['symbol']}:option_chain_error:{str(exc)[:120]}")
        record = {
            "schema_version": 1,
            "signal_id": signal_id,
            "captured_at": datetime.now(NY).isoformat(),
            "signal": signal,
            "selected_contract": selected,
            "contract_status": "selected" if selected else "blocked_no_qualified_contract",
            "execution_enabled": False,
            "can_submit_orders": False,
        }
        append_record(record, log_path)
        report["signals"].append(record)
        if selected and capture_quotes:
            import scripts.market_data as market_data

            market_data._load_env()  # noqa: SLF001
            headers = {
                "APCA-API-KEY-ID": market_data._ALPACA_KEY,  # noqa: SLF001
                "APCA-API-SECRET-KEY": market_data._ALPACA_SECRET,  # noqa: SLF001
            }
            capture_lifecycle_sample(
                "signal",
                selected["option_symbol"],
                bot="liquid_options_edge_shadow",
                headers=headers,
                trade_id=signal_id,
                underlying_symbol=signal["symbol"],
                context={"signal": signal, "contract_rank": selected.get("contract_rank")},
                path=QUOTE_PATH,
            )
    report["status"] = "ok"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=date.fromisoformat)
    parser.add_argument("--no-quote-capture", action="store_true")
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    report = build_report(args.date, capture_quotes=not args.no_quote_capture)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
