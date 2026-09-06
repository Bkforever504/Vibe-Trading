from datetime import date

from scripts import needs_review_queue


def test_needs_review_historical_fixture_uses_explicit_clock(monkeypatch, tmp_path):
    class FrozenDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 6, 30)

    monkeypatch.setattr(needs_review_queue, "date", FrozenDate)
    report = needs_review_queue.build_queue(guard_paths=[], outcome_path=tmp_path / "o",
                                             market_force_path=tmp_path / "m")
    assert report["date"] == "2026-06-30"
