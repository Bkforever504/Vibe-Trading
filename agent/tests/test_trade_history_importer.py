"""TDD tests for trade_history_importer.py"""
from __future__ import annotations
import json, sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.trade_history_importer import (
    NormalisedTrade, load_trades, derive_all_metrics,
    compute_pnl_smoothness, compute_green_months, compute_monthly_consistency,
    compute_worst_month_pct, compute_trade_frequency, compute_profit_factor,
    compute_max_drawdown, upsert_profile,
)


def _trades(rows: list[dict]) -> list[NormalisedTrade]:
    return [NormalisedTrade(r["date"], r.get("symbol","X"), r["pnl"], r.get("fee",0), r.get("notional",100)) for r in rows]


def test_pnl_smoothness_perfect_linear():
    trades = _trades([{"date": f"2026-0{m}-01", "pnl": 10.0} for m in range(1, 7)])
    assert compute_pnl_smoothness(trades) > 0.95


def test_pnl_smoothness_choppy():
    trades = _trades([
        {"date": "2026-01-01", "pnl":  50},
        {"date": "2026-01-05", "pnl": -45},
        {"date": "2026-01-10", "pnl":  60},
        {"date": "2026-01-15", "pnl": -55},
    ])
    assert compute_pnl_smoothness(trades) < 0.5


def test_green_months():
    trades = _trades([
        {"date": "2026-01-01", "pnl":  10},
        {"date": "2026-01-15", "pnl":   5},
        {"date": "2026-02-01", "pnl": -20},
        {"date": "2026-03-10", "pnl":   8},
    ])
    assert compute_green_months(trades) == 2


def test_monthly_consistency():
    trades = _trades([
        {"date": "2026-01-01", "pnl": 10},
        {"date": "2026-02-01", "pnl": -5},
        {"date": "2026-03-01", "pnl":  8},
        {"date": "2026-04-01", "pnl":  6},
    ])
    assert compute_monthly_consistency(trades) == pytest.approx(0.75)


def test_worst_month_pct_negative():
    trades = _trades([
        {"date": "2026-01-01", "pnl":  100, "notional": 1000},
        {"date": "2026-02-01", "pnl": -200, "notional": 1000},
    ])
    wm = compute_worst_month_pct(trades)
    assert wm < 0


def test_trade_frequency_buckets():
    selective  = _trades([{"date": f"2026-01-{i:02d}", "pnl": 1} for i in range(1, 6)])
    moderate   = _trades([{"date": f"2026-01-{i:02d}", "pnl": 1} for i in range(1, 21)])
    hyperact   = _trades([{"date": f"2026-01-{(i%28)+1:02d}", "pnl": 1} for i in range(40)])
    assert compute_trade_frequency(selective) == "selective"
    assert compute_trade_frequency(moderate)  == "moderate"
    assert compute_trade_frequency(hyperact)  == "hyperactive"


def test_profit_factor():
    trades = _trades([
        {"date": "2026-01-01", "pnl":  30},
        {"date": "2026-01-02", "pnl": -10},
        {"date": "2026-01-03", "pnl":  20},
    ])
    assert compute_profit_factor(trades) == pytest.approx(5.0)


def test_max_drawdown():
    trades = _trades([
        {"date": "2026-01-01", "pnl":  100},
        {"date": "2026-01-02", "pnl": -80},
        {"date": "2026-01-03", "pnl":  20},
    ])
    dd = compute_max_drawdown(trades)
    assert 0.3 < dd < 0.9


def test_derive_all_metrics_keys():
    trades = _trades([{"date": "2026-01-01", "pnl": 10}, {"date": "2026-01-02", "pnl": -2}])
    m = derive_all_metrics(trades)
    for key in ("trades","win_rate","realized_pnl","max_drawdown_pct","profit_factor",
                "pnl_smoothness","green_months","monthly_consistency","worst_month_pct",
                "avg_edge_per_trade","fee_adjusted_return","trade_frequency"):
        assert key in m, f"missing key: {key}"


def test_load_csv_polymarket(tmp_path):
    csv = tmp_path / "poly.csv"
    csv.write_text("timestamp,market,outcome,shares,profit_loss,fee\n"
                   "2026-01-15,BTC>50k,YES,100,25.0,1.0\n"
                   "2026-02-10,ETH>3k,NO,50,-10.0,0.5\n")
    trades = load_trades(csv)
    assert len(trades) == 2
    assert trades[0].pnl == 25.0


def test_load_csv_kalshi(tmp_path):
    csv = tmp_path / "kalshi.csv"
    csv.write_text("Date,Market,Contract,Action,Price,Contracts,Profit/Loss\n"
                   "2026-01-20,HIGHNY,HIGHNY-B72,buy,0.55,10,12.50\n"
                   "2026-02-05,HIGHCHI,HIGHCHI-T68,sell,0.30,5,-3.00\n")
    trades = load_trades(csv)
    assert len(trades) == 2
    assert trades[1].pnl == pytest.approx(-3.0)


def test_load_json_generic(tmp_path):
    jf = tmp_path / "trades.json"
    jf.write_text(json.dumps([
        {"date": "2026-01-10", "pnl": 50, "notional": 500, "fee": 2, "symbol": "SPY"},
        {"date": "2026-01-20", "pnl": -20, "notional": 200, "fee": 1, "symbol": "QQQ"},
    ]))
    trades = load_trades(jf)
    assert len(trades) == 2


def test_upsert_creates_and_updates(tmp_path):
    prof_file = tmp_path / "profiles.json"
    metrics = {"trades": 50, "win_rate": 0.60, "realized_pnl": 500,
               "max_drawdown_pct": 0.10, "profit_factor": 1.5,
               "pnl_smoothness": 0.75, "green_months": 4,
               "monthly_consistency": 0.66, "worst_month_pct": -0.05,
               "avg_edge_per_trade": 0.02, "fee_adjusted_return": 0.10,
               "trade_frequency": "selective"}

    p1 = upsert_profile("wallet_abc", "polymarket", "exported_history", "prediction_market",
                        metrics, prof_file)
    assert p1.handle == "wallet_abc"
    assert json.loads(prof_file.read_text())[0]["handle"] == "wallet_abc"

    metrics2 = {**metrics, "trades": 80, "realized_pnl": 900}
    p2 = upsert_profile("wallet_abc", "polymarket", "exported_history", "prediction_market",
                        metrics2, prof_file)
    data = json.loads(prof_file.read_text())
    assert len(data) == 1          # upserted, not duplicated
    assert data[0]["trades"] == 80
