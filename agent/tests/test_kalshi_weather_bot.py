from __future__ import annotations

from datetime import datetime, timezone

from strategies.kalshi_weather_bot import (
    WEATHER_SERIES,
    build_report,
    kalshi_taker_fee,
    market_bucket,
    parse_orderbook,
)


def _market(*, status: str = "active", result: str = "") -> dict:
    return {
        "ticker": "KXHIGHNY-26JUL16-B93.5",
        "event_ticker": "KXHIGHNY-26JUL16",
        "title": "Will the high temp in NYC be between 93-94?",
        "status": status,
        "result": result,
        "strike_type": "between",
        "floor_strike": 93,
        "cap_strike": 94,
        "occurrence_datetime": "2026-07-16T14:00:00Z",
        "close_time": "2026-07-17T04:59:00Z",
        "yes_bid_dollars": "0.2800",
        "yes_ask_dollars": "0.3000",
        "no_bid_dollars": "0.6900",
        "no_ask_dollars": "0.7200",
        "volume_fp": "1000.00",
        "open_interest_fp": "500.00",
        "rules_primary": "Central Park NWS daily climate report.",
    }


def _book() -> dict:
    return {
        "orderbook_fp": {
            "yes_dollars": [["0.2500", "10.00"], ["0.2800", "20.00"]],
            "no_dollars": [["0.6500", "10.00"], ["0.7000", "15.00"]],
        }
    }


def test_fixed_point_orderbook_derives_reciprocal_asks_and_depth() -> None:
    quote = parse_orderbook(_book())
    assert quote["yes_bid"] == 0.28
    assert quote["yes_ask"] == 0.30
    assert quote["no_bid"] == 0.70
    assert quote["no_ask"] == 0.72
    assert quote["yes_ask_size"] == 15.0
    assert quote["no_ask_size"] == 20.0


def test_market_bucket_matches_kalshi_strike_semantics() -> None:
    between = market_bucket(_market())
    assert between.contains(93)
    assert between.contains(94)
    assert not between.contains(95)

    below = market_bucket({"strike_type": "less", "cap_strike": 89, "floor_strike": None})
    assert below.contains(88)
    assert not below.contains(89)

    above = market_bucket({"strike_type": "greater", "floor_strike": 96, "cap_strike": None})
    assert above.contains(97)
    assert not above.contains(96)


def test_fee_model_is_conservative_and_rounded_up_to_cent() -> None:
    assert kalshi_taker_fee(0.50, 1) == 0.02
    assert kalshi_taker_fee(0.10, 1) == 0.01
    assert kalshi_taker_fee(0.50, 10) == 0.18


def test_series_registry_uses_exact_nws_reporting_sites() -> None:
    assert WEATHER_SERIES["KXHIGHNY"].station_code == "KNYC"
    assert WEATHER_SERIES["KXHIGHCHI"].station_code == "KMDW"
    assert WEATHER_SERIES["KXHIGHAUS"].station_code == "KAUS"
    assert WEATHER_SERIES["KXHIGHTHOU"].station_code == "KHOU"
    assert len(WEATHER_SERIES) >= 13


def test_report_opens_only_one_promotion_grade_position_per_event(tmp_path) -> None:
    second = {**_market(), "ticker": "KXHIGHNY-26JUL16-T96", "strike_type": "greater", "floor_strike": 96, "cap_strike": None}

    class Client:
        def markets(self, series_ticker):
            return [_market(), second] if series_ticker == "KXHIGHNY" else []

        def orderbook(self, ticker):
            return _book()

        def ensembles(self, station, target_date, unit):
            values = [93.2] * 30
            return {"gfs_gefs": values, "ecmwf_ifs": values, "icon_eu": values}

        def market(self, ticker):
            return _market()

    report = build_report(Client(), state_path=tmp_path / "state.json", now=datetime(2026, 7, 15, 12, tzinfo=timezone.utc))

    assert report["events_discovered"] == 1
    assert report["markets_modeled"] == 2
    assert len(report["new_paper_positions"]) == 1
    position = report["new_paper_positions"][0]
    assert position["event_ticker"] == "KXHIGHNY-26JUL16"
    assert position["promotion_grade"] is True
    assert position["contracts"] >= 1
    assert position["risk_dollars"] <= 5.0
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False


def test_missing_model_family_fails_closed(tmp_path) -> None:
    class Client:
        def markets(self, series_ticker):
            return [_market()] if series_ticker == "KXHIGHNY" else []

        def orderbook(self, ticker):
            return _book()

        def ensembles(self, station, target_date, unit):
            return {"gfs_gefs": [93.0] * 30, "ecmwf_ifs": [93.0] * 30}

        def market(self, ticker):
            return _market()

    report = build_report(Client(), state_path=tmp_path / "state.json", now=datetime(2026, 7, 15, 12, tzinfo=timezone.utc))
    assert report["opportunity_count"] == 0
    assert report["new_paper_positions"] == []


def test_report_prefers_bulk_orderbooks(tmp_path) -> None:
    class Client:
        bulk_calls = []

        def markets(self, series_ticker):
            return [_market()] if series_ticker == "KXHIGHNY" else []

        def orderbooks(self, tickers):
            self.bulk_calls.append(list(tickers))
            return {tickers[0]: _book()}

        def orderbook(self, ticker):
            raise AssertionError("single orderbook endpoint should not be used")

        def ensembles(self, station, target_date, unit):
            return {name: [93.0] * 30 for name in ("gfs_gefs", "ecmwf_ifs", "icon_eu")}

        def market(self, ticker):
            return _market()

    client = Client()
    report = build_report(client, state_path=tmp_path / "state.json", now=datetime(2026, 7, 15, 12, tzinfo=timezone.utc))
    assert client.bulk_calls == [["KXHIGHNY-26JUL16-B93.5"]]
    assert report["markets_modeled"] == 1


def test_finalized_market_closes_position_using_exchange_result(tmp_path) -> None:
    class Client:
        finalized = False

        def markets(self, series_ticker):
            return [_market()] if series_ticker == "KXHIGHNY" and not self.finalized else []

        def orderbook(self, ticker):
            return _book()

        def ensembles(self, station, target_date, unit):
            return {name: [93.0] * 30 for name in ("gfs_gefs", "ecmwf_ifs", "icon_eu")}

        def market(self, ticker):
            return _market(status="finalized", result="yes") if self.finalized else _market()

    client = Client()
    state = tmp_path / "state.json"
    first = build_report(client, state_path=state, now=datetime(2026, 7, 15, 12, tzinfo=timezone.utc))
    assert len(first["new_paper_positions"]) == 1
    client.finalized = True
    second = build_report(client, state_path=state, now=datetime(2026, 7, 17, 12, tzinfo=timezone.utc))
    assert second["open_paper_positions_count"] == 0
    assert second["closed_paper_positions_count"] == 1
    assert second["newly_closed_positions"][0]["exit_reason"] == "kalshi_finalized_yes"
    assert second["newly_closed_positions"][0]["pnl_dollars"] > 0
