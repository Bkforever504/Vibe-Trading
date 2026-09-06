from datetime import datetime, timedelta

from research.spy_5m_0dte_orb_replay import build_report, detect_signals, replay_option_path


def _bar(stamp, close, high=None, low=None):
    return {"timestamp": stamp.isoformat(), "open": close, "high": high or close, "low": low or close, "close": close}


def _orb_bars(day=datetime(2026, 9, 14, 9, 30)):
    rows = [_bar(day + timedelta(minutes=i), 100, 101, 99) for i in range(5)]
    return rows + [_bar(day + timedelta(minutes=5), 102, 102, 101), _bar(day + timedelta(minutes=6), 98, 99, 97)]


def test_detects_only_first_closed_break_on_eligible_day():
    signals = detect_signals(_orb_bars())
    assert len(signals) == 1
    assert signals[0]["direction"] == "call"
    assert signals[0]["signal_bar_completed_at"].startswith("2026-09-14T09:36")
    assert signals[0]["execution_enabled"] is False


def test_excludes_non_mwf_session():
    tuesday = datetime(2026, 9, 15, 9, 30)
    assert detect_signals(_orb_bars(tuesday)) == []


def test_replays_at_ask_then_exits_at_bid():
    signal = detect_signals(_orb_bars())[0]
    decision = datetime.fromisoformat(signal["signal_bar_completed_at"])
    outcome = replay_option_path(signal, [
        {"timestamp": decision.isoformat(), "bid": 0.98, "ask": 1.00},
        {"timestamp": (decision + timedelta(minutes=1)).isoformat(), "bid": 2.05, "ask": 2.10},
    ])
    assert outcome["status"] == "resolved_executable_quote_path"
    assert outcome["outcome"] == "target"
    assert outcome["entry_ask"] == 1.0
    assert outcome["exit_bid"] == 2.05


def test_report_does_not_convert_missing_quotes_to_assumed_fills():
    report = build_report(_orb_bars())
    assert report["resolved_option_quote_paths"] == 0
    assert report["outcomes"][0]["option_outcome"]["reason"] == "timestamped_option_bid_ask_required"
    assert report["can_submit_orders"] is False
