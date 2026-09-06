from scripts import wolves_bbr_shadow as wolves


class _Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {"bars": {"SPY": []}}


def test_fetch_page_retries_transient_connection_failures(monkeypatch):
    monkeypatch.setattr(wolves, "_credentials", lambda: {"key": "redacted"})
    calls = []
    sleeps = []

    def requester(*args, **kwargs):
        calls.append((args, kwargs))
        if len(calls) < 3:
            raise ConnectionError("transient")
        return _Response()

    payload = wolves._fetch_page({}, requester=requester, sleeper=sleeps.append)
    assert payload == {"bars": {"SPY": []}}
    assert len(calls) == 3
    assert sleeps == [0.35, 0.7]
