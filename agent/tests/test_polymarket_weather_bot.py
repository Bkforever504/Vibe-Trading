from __future__ import annotations

from datetime import datetime, timezone

from strategies.polymarket_weather_bot import (
    PublicClient,
    Station,
    TemperatureBucket,
    _ladder_opportunities,
    bucket_probability,
    build_report,
    executable_quote,
    parse_bucket,
    parse_event,
    resolved_yes_price,
)


def test_public_client_geoblock_uses_official_endpoint() -> None:
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"blocked": True, "country": "US", "region": "TX"}

    class Session:
        calls = []

        def get(self, url, params, timeout):
            self.calls.append((url, params, timeout))
            return Response()

    session = Session()
    result = PublicClient(session).geoblock()
    assert result == {"blocked": True, "country": "US", "region": "TX"}
    assert session.calls == [("https://polymarket.com/api/geoblock", {}, 20)]


def _event() -> dict:
    return {
        "id": "event-1",
        "slug": "highest-temperature-in-sao-paulo-on-july-15-2026",
        "title": "Highest temperature in Sao Paulo on July 15?",
        "endDate": "2026-07-15T23:00:00Z",
        "description": "highest temperature recorded at the airport in degrees Celsius. https://www.wunderground.com/history/daily/br/guarulhos/SBGR.",
        "markets": [{
            "id": "market-19",
            "question": "Will the highest temperature be 19 C?",
            "groupItemTitle": "19°C",
            "outcomes": '["Yes", "No"]',
            "clobTokenIds": '["yes-token", "no-token"]',
            "acceptingOrders": True,
            "feeType": "weather_fees",
        }],
    }


def test_bucket_parser_and_boundaries() -> None:
    assert parse_bucket("15°C or below", "C") == TemperatureBucket("15°C or below", 15, "at_or_below", "C")
    assert parse_bucket("25°C or higher", "C").contains(26)
    assert parse_bucket("19°C", "C").contains(19)
    assert not parse_bucket("19°C", "C").contains(20)


def test_event_requires_known_resolution_station_and_current_date() -> None:
    parsed = parse_event(_event(), today=datetime(2026, 7, 15).date())
    assert parsed is not None
    assert parsed["station"]["code"] == "SBGR"
    assert parsed["markets"][0]["yes_token_id"] == "yes-token"
    unknown = _event()
    unknown["description"] = unknown["description"].replace("SBGR", "ZZZZ")
    assert parse_event(unknown, today=datetime(2026, 7, 15).date()) is None
    assert parse_event(_event(), today=datetime(2026, 7, 16).date()) is None


def test_executable_quote_uses_best_prices() -> None:
    quote = executable_quote({"bids": [{"price": "0.31", "size": "10"}, {"price": "0.34", "size": "5"}], "asks": [{"price": "0.45", "size": "8"}, {"price": "0.42", "size": "7"}]})
    assert quote == {"bid": 0.34, "ask": 0.42, "spread": 0.07999999999999996}


def test_ensemble_probability_uses_resolution_rounding() -> None:
    bucket = TemperatureBucket("19 C", 19, "exact", "C")
    assert bucket_probability(bucket, [18.5, 18.6, 19.4, 19.5]) == 0.75


def test_settlement_requires_closed_extreme_outcome_price() -> None:
    event = {"markets": [{"id": "m1", "closed": True, "outcomes": '["Yes", "No"]', "outcomePrices": '["1", "0"]'}]}
    assert resolved_yes_price(event, "m1") == 1.0
    event["markets"][0]["outcomePrices"] = '["0.5", "0.5"]'
    assert resolved_yes_price(event, "m1") is None


def test_build_report_opens_paper_position_and_has_no_execution(tmp_path) -> None:
    class Client:
        def events(self):
            return [_event()]

        def ensembles(self, station: Station, target_date: str, unit: str):
            assert station.code == "SBGR"
            return {"gfs_gefs": [19.0] * 24 + [20.0] * 6, "ecmwf_ifs": [19.0] * 25 + [20.0] * 5, "icon_eu": [19.0] * 26 + [20.0] * 4}

        def book(self, token_id: str):
            return {"bids": [{"price": "0.28", "size": "100"}], "asks": [{"price": "0.30", "size": "100"}]}

    report = build_report(Client(), state_path=tmp_path / "state.json", now=datetime(2026, 7, 15, 12, tzinfo=timezone.utc))
    assert report["opportunity_count"] == 1
    assert len(report["new_paper_positions"]) == 1
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["wallet_connected"] is False
    assert report["new_paper_positions"][0]["risk_dollars"] <= 5.0
    assert report["venue_eligibility"]["eligible_for_order_submission"] is False
    assert report["venue_eligibility"]["status"] == "unverified"


def test_geoblocked_location_is_recorded_and_fails_closed(tmp_path) -> None:
    class Client:
        def geoblock(self):
            return {"blocked": True, "country": "US", "region": "TX"}

        def events(self):
            return []

    report = build_report(Client(), state_path=tmp_path / "state.json", now=datetime(2026, 7, 15, 12, tzinfo=timezone.utc))
    assert report["venue_eligibility"] == {
        "source": "https://polymarket.com/api/geoblock",
        "checked": True,
        "blocked": True,
        "country": "US",
        "region": "TX",
        "status": "blocked",
        "eligible_for_order_submission": False,
    }
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False


def test_wide_spread_fails_closed(tmp_path) -> None:
    class Client:
        def events(self):
            return [_event()]

        def ensembles(self, station, target_date, unit):
            return {"gfs_gefs": [19.0] * 30, "ecmwf_ifs": [19.0] * 30, "icon_eu": [19.0] * 30}

        def book(self, token_id):
            return {"bids": [{"price": "0.10", "size": "100"}], "asks": [{"price": "0.30", "size": "100"}]}

    report = build_report(Client(), state_path=tmp_path / "state.json", now=datetime(2026, 7, 15, 12, tzinfo=timezone.utc))
    assert report["opportunity_count"] == 0
    assert report["new_paper_positions"] == []


def test_closed_market_is_not_reopened_in_same_state(tmp_path) -> None:
    class Client:
        bid = "0.28"

        def events(self):
            return [_event()]

        def ensembles(self, station, target_date, unit):
            return {"gfs_gefs": [19.0] * 30, "ecmwf_ifs": [19.0] * 30, "icon_eu": [19.0] * 30}

        def book(self, token_id):
            return {"bids": [{"price": self.bid, "size": "100"}], "asks": [{"price": "0.30", "size": "100"}]}

    client = Client()
    state = tmp_path / "state.json"
    first = build_report(client, state_path=state, now=datetime(2026, 7, 15, 12, tzinfo=timezone.utc))
    assert len(first["new_paper_positions"]) == 1
    client.bid = "0.50"
    second = build_report(client, state_path=state, now=datetime(2026, 7, 15, 13, tzinfo=timezone.utc))
    assert second["closed_paper_positions_count"] == 1
    assert second["new_paper_positions"] == []
    assert second["open_paper_positions"] == []


def test_large_probability_disagreement_fails_closed(tmp_path) -> None:
    class Client:
        def events(self):
            return [_event()]

        def ensembles(self, station, target_date, unit):
            return {"gfs_gefs": [19.0] * 30, "ecmwf_ifs": [19.0] * 15 + [20.0] * 15, "icon_eu": [19.0] * 30}

        def book(self, token_id):
            return {"bids": [{"price": "0.18", "size": "100"}], "asks": [{"price": "0.20", "size": "100"}]}

    report = build_report(Client(), state_path=tmp_path / "state.json", now=datetime(2026, 7, 15, 12, tzinfo=timezone.utc))
    modeled = report["modeled_markets"][0]
    assert modeled["model_edges"]["ecmwf_ifs"] > 0.10
    assert modeled["model_probability_spread"] == 0.5
    assert modeled["model_agreement"] is False
    assert report["opportunity_count"] == 0


def test_forecasts_are_cached_for_six_hours_while_books_refresh(tmp_path) -> None:
    class Client:
        ensemble_calls = 0
        book_calls = 0

        def events(self):
            return [_event()]

        def ensembles(self, station, target_date, unit):
            self.ensemble_calls += 1
            return {"gfs_gefs": [19.0] * 30, "ecmwf_ifs": [19.0] * 30, "icon_eu": [19.0] * 30}

        def book(self, token_id):
            self.book_calls += 1
            return {"bids": [{"price": "0.10", "size": "100"}], "asks": [{"price": "0.30", "size": "100"}]}

    client, state = Client(), tmp_path / "state.json"
    first = build_report(client, state_path=state, now=datetime(2026, 7, 15, 12, tzinfo=timezone.utc))
    second = build_report(client, state_path=state, now=datetime(2026, 7, 15, 13, tzinfo=timezone.utc))
    assert client.ensemble_calls == 1
    assert client.book_calls == 2
    assert first["modeled_markets"][0]["forecast_status"] == "fresh_model_cycle"
    assert second["modeled_markets"][0]["forecast_status"] == "cached_under_6h"


def test_build_report_requires_all_three_model_families(tmp_path) -> None:
    class Client:
        def events(self):
            return [_event()]

        def ensembles(self, station, target_date, unit):
            return {"gfs_gefs": [19.0] * 30, "ecmwf_ifs": [19.0] * 30}

        def book(self, token_id):
            raise AssertionError("books must not be requested without all model families")

    report = build_report(Client(), state_path=tmp_path / "state.json", now=datetime(2026, 7, 15, 12, tzinfo=timezone.utc))
    assert report["markets_modeled"] == 0
    assert report["opportunity_count"] == 0
    assert "icon_eu" in report["errors"][0]
    assert report["risk_limits"]["independent_models_required"] == 3


def test_station_local_date_prevents_premature_utc_expiry() -> None:
    event = _event()
    event.update({
        "slug": "highest-temperature-in-seattle-on-july-14-2026",
        "title": "Highest temperature in Seattle on July 14?",
        "description": "temperature in degrees Fahrenheit. https://www.wunderground.com/history/daily/us/wa/seattle/KSEA.",
    })
    event["markets"][0]["groupItemTitle"] = "75F"
    assert parse_event(event, now=datetime(2026, 7, 15, 4, tzinfo=timezone.utc)) is not None
    assert parse_event(event, now=datetime(2026, 7, 15, 8, tzinfo=timezone.utc)) is None


def test_city_fallback_and_london_city_station_mapping() -> None:
    event = _event()
    event.update({
        "slug": "highest-temperature-in-hong-kong-on-july-15-2026",
        "title": "Highest temperature in Hong Kong on July 15?",
        "description": "temperature in degrees Celsius with Weather Underground as the resolution source.",
    })
    assert parse_event(event, today=datetime(2026, 7, 15).date())["station"]["code"] == "VHHH"
    event.update({
        "slug": "highest-temperature-in-london-on-july-15-2026",
        "title": "Highest temperature in London on July 15?",
        "description": "temperature in degrees Celsius. https://www.wunderground.com/history/daily/gb/london/EGLC.",
    })
    assert parse_event(event, today=datetime(2026, 7, 15).date())["station"]["code"] == "EGLC"


def test_ladder_groups_only_adjacent_buckets() -> None:
    def row(value: int, edge: float) -> dict:
        return {"event_id": "e1", "bucket": {"value": value}, "edge": edge}

    assert _ladder_opportunities([row(20, 0.4), row(22, 0.3)]) == []
    groups = _ladder_opportunities([row(20, 0.2), row(21, 0.3), row(22, 0.1), row(30, 0.9)])
    assert [leg["bucket"]["value"] for leg in groups[0][1]] == [20, 21, 22]


def test_ladder_is_all_or_none_and_respects_event_risk_cap(tmp_path) -> None:
    event = _event()
    second = dict(event["markets"][0])
    second.update({"id": "market-20", "groupItemTitle": "20C", "clobTokenIds": '["yes-token-20", "no-token-20"]'})
    event["markets"].append(second)

    class Client:
        def events(self):
            return [event]

        def ensembles(self, station, target_date, unit):
            values = [19.0] * 15 + [20.0] * 15
            return {"gfs_gefs": values, "ecmwf_ifs": values, "icon_eu": values}

        def book(self, token_id):
            return {"bids": [{"price": "0.09", "size": "100"}], "asks": [{"price": "0.10", "size": "100"}]}

    report = build_report(Client(), state_path=tmp_path / "state.json", now=datetime(2026, 7, 15, 12, tzinfo=timezone.utc))
    opened = report["new_paper_positions"]
    assert len(opened) == 2
    assert sum(position["risk_dollars"] for position in opened) <= 5.0
    assert {position["sizing_method"] for position in opened} == {"fixed_event_cap_ladder_kelly_telemetry"}
    assert all(position["kelly_fraction"] <= 0.25 for position in opened)


def test_asymmetric_research_candidate_cannot_open_without_model_agreement(tmp_path) -> None:
    class Client:
        def events(self):
            return [_event()]

        def ensembles(self, station, target_date, unit):
            return {
                "gfs_gefs": [19.0] * 18 + [20.0] * 12,
                "ecmwf_ifs": [20.0] * 30,
                "icon_eu": [20.0] * 30,
            }

        def book(self, token_id):
            return {"bids": [{"price": "0.04", "size": "100"}], "asks": [{"price": "0.05", "size": "100"}]}

    report = build_report(Client(), state_path=tmp_path / "state.json", now=datetime(2026, 7, 15, 12, tzinfo=timezone.utc))
    assert len(report["asymmetric_candidates"]) == 1
    assert report["opportunity_count"] == 0
    assert report["new_paper_positions"] == []


def test_near_miss_cohort_is_separate_and_resolves_without_opening_position(tmp_path) -> None:
    class Client:
        active = True

        def events(self):
            return [_event()] if self.active else []

        def ensembles(self, station, target_date, unit):
            values = [19.0] * 6 + [20.0] * 24
            return {"gfs_gefs": values, "ecmwf_ifs": values, "icon_eu": values}

        def book(self, token_id):
            return {"bids": [{"price": "0.11", "size": "100"}], "asks": [{"price": "0.12", "size": "100"}]}

        def event(self, event_id):
            resolved = _event()
            resolved["markets"][0].update({"closed": True, "outcomePrices": '["1", "0"]'})
            return resolved

    client = Client()
    state = tmp_path / "state.json"
    first = build_report(client, state_path=state, now=datetime(2026, 7, 15, 12, tzinfo=timezone.utc))
    assert len(first["near_miss_candidates"]) == 1
    assert len(first["new_near_miss_observations"]) == 1
    assert first["new_paper_positions"] == []
    client.active = False
    second = build_report(client, state_path=state, now=datetime(2026, 7, 16, 12, tzinfo=timezone.utc))
    assert second["closed_near_miss_observations_count"] == 1
    assert second["newly_resolved_near_misses"][0]["would_win"] is True
    assert second["open_near_miss_observations_count"] == 0
