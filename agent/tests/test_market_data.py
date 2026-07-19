from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.market_data as market_data


def _reset_market_data(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    monkeypatch.setattr(market_data, "_ALPACA_KEY", None)
    monkeypatch.setattr(market_data, "_ALPACA_SECRET", None)
    monkeypatch.setattr(market_data, "_ENV_PATH", tmp_path / ".env")


def _install_fake_alpaca(monkeypatch, df: pd.DataFrame) -> None:
    class FakeBars:
        def __init__(self, frame: pd.DataFrame) -> None:
            self.df = frame

    class FakeClient:
        def __init__(self, api_key: str | None = None, secret_key: str | None = None) -> None:
            self.api_key = api_key
            self.secret_key = secret_key

        def get_stock_bars(self, request):
            return FakeBars(df)

    class FakeRequest:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    fake_historical = types.ModuleType("alpaca.data.historical")
    fake_historical.StockHistoricalDataClient = FakeClient
    fake_requests = types.ModuleType("alpaca.data.requests")
    fake_requests.StockBarsRequest = FakeRequest
    fake_timeframe = types.ModuleType("alpaca.data.timeframe")
    fake_timeframe.TimeFrame = types.SimpleNamespace(Day="1Day")

    monkeypatch.setitem(sys.modules, "alpaca", types.ModuleType("alpaca"))
    monkeypatch.setitem(sys.modules, "alpaca.data", types.ModuleType("alpaca.data"))
    monkeypatch.setitem(sys.modules, "alpaca.data.historical", fake_historical)
    monkeypatch.setitem(sys.modules, "alpaca.data.requests", fake_requests)
    monkeypatch.setitem(sys.modules, "alpaca.data.timeframe", fake_timeframe)


def test_load_env_reads_alpaca_keys_from_agent_env(monkeypatch, tmp_path: Path) -> None:
    _reset_market_data(monkeypatch, tmp_path)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ALPACA_API_KEY=paper-key\nALPACA_SECRET_KEY=paper-secret\n",
        encoding="utf-8",
    )

    market_data._load_env()

    assert market_data._ALPACA_KEY == "paper-key"
    assert market_data._ALPACA_SECRET == "paper-secret"


def test_data_source_reflects_key_availability(monkeypatch, tmp_path: Path) -> None:
    _reset_market_data(monkeypatch, tmp_path)
    assert market_data.data_source() == "yfinance"

    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")
    monkeypatch.setattr(market_data, "_ALPACA_KEY", None)
    monkeypatch.setattr(market_data, "_ALPACA_SECRET", None)

    assert market_data.data_source() == "alpaca"


def test_fetch_ohlcv_alpaca_flattens_multiindex_and_strips_timezone(monkeypatch, tmp_path: Path) -> None:
    _reset_market_data(monkeypatch, tmp_path)
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")
    idx = pd.MultiIndex.from_product(
        [["QQQ"], pd.date_range("2026-06-24", periods=2, tz="UTC")],
        names=["symbol", "timestamp"],
    )
    df = pd.DataFrame(
        {
            "open": [1.0, 2.0],
            "high": [1.5, 2.5],
            "low": [0.5, 1.5],
            "close": [1.2, 2.2],
            "volume": [100, 200],
            "trade_count": [10, 20],
        },
        index=idx,
    )
    _install_fake_alpaca(monkeypatch, df)

    result = market_data.fetch_ohlcv("QQQ", lookback_days=5)

    assert list(result.columns) == ["open", "high", "low", "close", "volume"]
    assert result.index.name == "timestamp"
    assert result.index.tz is None
    assert result["close"].tolist() == [1.2, 2.2]


def test_fetch_close_alpaca_pivots_multiindex_to_symbol_columns(monkeypatch, tmp_path: Path) -> None:
    _reset_market_data(monkeypatch, tmp_path)
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")
    idx = pd.MultiIndex.from_product(
        [["QQQ", "GLD"], pd.date_range("2026-06-24", periods=2, tz="UTC")],
        names=["symbol", "timestamp"],
    )
    df = pd.DataFrame(
        {
            "open": [1.0, 2.0, 10.0, 20.0],
            "high": [1.0, 2.0, 10.0, 20.0],
            "low": [1.0, 2.0, 10.0, 20.0],
            "close": [100.0, 101.0, 200.0, 202.0],
            "volume": [100, 100, 200, 200],
        },
        index=idx,
    )
    _install_fake_alpaca(monkeypatch, df)

    result = market_data.fetch_close(["QQQ", "GLD"], lookback_days=5)

    assert list(result.columns) == ["GLD", "QQQ"]
    assert result.index.tz is None
    assert result.loc[pd.Timestamp("2026-06-24"), "QQQ"] == 100.0
    assert result.loc[pd.Timestamp("2026-06-25"), "GLD"] == 202.0


def test_fetch_close_alpaca_handles_single_symbol_non_multiindex(monkeypatch, tmp_path: Path) -> None:
    _reset_market_data(monkeypatch, tmp_path)
    monkeypatch.setenv("ALPACA_API_KEY", "key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret")
    idx = pd.date_range("2026-06-24", periods=2, tz="UTC")
    df = pd.DataFrame({"close": [10.0, 11.0]}, index=idx)
    _install_fake_alpaca(monkeypatch, df)

    result = market_data.fetch_close(["SPY"], lookback_days=5)

    assert list(result.columns) == ["SPY"]
    assert result.index.tz is None
    assert result["SPY"].tolist() == [10.0, 11.0]


def test_fetch_vix_context_parses_cboe_csv(monkeypatch) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def read(self) -> bytes:
            return b"DATE,OPEN,HIGH,LOW,CLOSE\n2026-06-26,17,18,16,21.34\n"

    monkeypatch.setattr(market_data.urllib.request, "urlopen", lambda *args, **kwargs: FakeResponse())

    context = market_data.fetch_vix_context()

    assert context == {
        "source": "cboe_vix_history",
        "date": "2026-06-26",
        "close": 21.34,
        "above_20": True,
        "regime": "elevated",
    }


def test_fetch_vix_context_returns_unavailable_on_error(monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise OSError("network down")

    monkeypatch.setattr(market_data.urllib.request, "urlopen", fail)

    context = market_data.fetch_vix_context()

    assert context["available"] is False
    assert context["source"] == "cboe_vix_history"
    assert "network down" in context["error"]


def test_fetch_vix_term_structure_context_parses_cboe_vix_and_vix3m(monkeypatch) -> None:
    class FakeResponse:
        def __init__(self, raw: bytes) -> None:
            self.raw = raw

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def read(self) -> bytes:
            return self.raw

    def fake_urlopen(url: str, *args, **kwargs):
        if "VIX3M_History" in url:
            return FakeResponse(b"DATE,OPEN,HIGH,LOW,CLOSE\n2026-06-26,19,20,18,20.00\n")
        return FakeResponse(b"DATE,OPEN,HIGH,LOW,CLOSE\n2026-06-26,17,18,16,24.00\n")

    monkeypatch.setattr(market_data.urllib.request, "urlopen", fake_urlopen)

    context = market_data.fetch_vix_term_structure_context()

    assert context == {
        "source": "cboe_vix_vix3m_history",
        "date": "2026-06-26",
        "vix": 24.0,
        "vix3m": 20.0,
        "vix_over_vix3m": 1.2,
        "vix3m_over_vix": 0.8333,
        "regime": "backwardation",
    }


def test_fetch_vix_term_structure_context_returns_unavailable_on_error(monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise OSError("cboe down")

    monkeypatch.setattr(market_data.urllib.request, "urlopen", fail)

    context = market_data.fetch_vix_term_structure_context()

    assert context["available"] is False
    assert context["source"] == "cboe_vix_vix3m_history"
    assert "cboe down" in context["error"]
