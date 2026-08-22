from __future__ import annotations

from datetime import datetime, timedelta, timezone

from strategies.flip_option_quote_subscription import request_option_quote, requested_option_symbols


def test_candidate_subscription_expires(tmp_path) -> None:
    path = tmp_path / "subscriptions.json"
    now = datetime(2026, 8, 17, 14, 0, tzinfo=timezone.utc)

    request_option_quote("spy260817c00780000", path=path, ttl_seconds=10, now=now)

    assert requested_option_symbols(path=path, now=now + timedelta(seconds=9)) == {
        "SPY260817C00780000"
    }
    assert requested_option_symbols(path=path, now=now + timedelta(seconds=11)) == set()


def test_new_request_prunes_expired_subscriptions(tmp_path) -> None:
    path = tmp_path / "subscriptions.json"
    now = datetime(2026, 8, 17, 14, 0, tzinfo=timezone.utc)
    request_option_quote("SPY260817C00780000", path=path, ttl_seconds=5, now=now)
    request_option_quote("QQQ260817P00690000", path=path, ttl_seconds=20, now=now + timedelta(seconds=6))

    assert requested_option_symbols(path=path, now=now + timedelta(seconds=7)) == {
        "QQQ260817P00690000"
    }
