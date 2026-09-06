from datetime import datetime, timezone
from scripts.options_nbbo_evidence import analyze

NOW = datetime(2026, 9, 4, 12, 0, 30, tzinfo=timezone.utc)


def quote(symbol, bid, ask, ask_size, **extra):
    return {'symbol': symbol, 'bid': bid, 'ask': ask, 'ask_size': ask_size, 'quote_timestamp': '2026-09-04T12:00:00Z',
            'quote_scope': 'databento_opra_cbbo_1s', 'provenance': {'provider': 'databento', 'licensed_consolidated_nbbo': True}, **extra}


def test_two_numeric_signals_create_bias_but_quote_right_does_not_fake_trade_direction():
    result = analyze([quote('SPY260904P00700000', 2, 2.2, 100, iv=.30), quote('SPY260904C00750000', 1, 1.1, 20, iv=.20)], 'SPY', as_of=NOW)
    assert result['direction'] == 'SHORT'
    assert result['aligned_signal_count'] == 2
    assert result['evidence_numeric']['put_call_dollar_premium_ratio'] == 10
    assert result['evidence_numeric']['unusual_prints_count'] == 0


def test_one_signal_is_neutral_and_stale_quotes_are_missing():
    result = analyze([quote('SPY260904P00700000', 2, 2.2, 100), quote('SPY260904C00750000', 1, 1.1, 20)], 'SPY', as_of=NOW)
    assert result['direction'] == 'NEUTRAL'
    stale = analyze([{**quote('SPY260904P00700000', 2, 2.2, 100), 'quote_timestamp': '2026-09-04T11:59:00Z'}], 'SPY', as_of=NOW)
    assert stale['status'] == 'missing'
    assert stale['evidence_numeric']['put_call_dollar_premium_ratio'] is None


def test_verified_ask_aggressing_print_is_required_for_unusual_direction():
    rows = [quote('SPY260904C00750000', 1, 1.1, 100, iv=.2), quote('SPY260904P00700000', 1, 1.1, 100, iv=.2),
            {**quote('SPY260904C00750000', 1, 1.1, 1), 'record_type': 'trade', 'verified': True, 'trade_id': 'one', 'price': 2, 'size': 300, 'aggressor_side': 'ask'}]
    result = analyze(rows, 'SPY', as_of=NOW)
    assert result['unusual_prints'][0]['direction'] == 'LONG'
    assert result['evidence_numeric']['unusual_prints_dollar_total'] == 60000
