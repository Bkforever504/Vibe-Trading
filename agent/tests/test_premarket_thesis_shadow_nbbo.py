from datetime import datetime
from zoneinfo import ZoneInfo
from scripts.premarket_thesis_shadow import build_report

ET = ZoneInfo('America/New_York')
NOW = datetime(2026, 9, 4, 8, 0, 30, tzinfo=ET)


def q(symbol, size, iv, at='2026-09-04T12:00:00Z'):
    return {'symbol': symbol, 'bid': 1, 'ask': 1.2, 'ask_size': size, 'iv': iv, 'quote_timestamp': at,
            'quote_scope': 'databento_opra_cbbo_1s', 'provenance': {'licensed_consolidated_nbbo': True}}


def test_frozen_nbbo_numbers_require_two_aligned_signals():
    report = build_report(radar={}, nbbo_rows=[q('SPY260904P00700000', 100, .3), q('SPY260904C00750000', 10, .2)], now_et=NOW)
    spy = next(x for x in report['theses'] if x['symbol'] == 'SPY')
    assert spy['direction'] == 'SHORT' and spy['fresh'] is True
    assert spy['evidence_numeric']['put_call_dollar_premium_ratio'] == 10
    assert spy['sources_used'] == ['databento_opra_nbbo']


def test_missing_nbbo_is_no_bias_for_all_symbols():
    report = build_report(radar={}, nbbo_rows=[], nbbo_status='timeout', now_et=NOW)
    assert report['status'] == 'missing'
    assert len(report['theses']) == 3
    assert {x['direction'] for x in report['theses']} == {'NO_BIAS'}
    assert all(x['evidence_numeric']['put_call_dollar_premium_ratio'] is None for x in report['theses'])


def test_one_signal_and_stale_quotes_do_not_create_direction():
    one = build_report(radar={}, nbbo_rows=[q('SPY260904P00700000', 100, .2), q('SPY260904C00750000', 10, .2)], now_et=NOW)
    assert next(x for x in one['theses'] if x['symbol'] == 'SPY')['direction'] == 'NO_BIAS'
    stale = build_report(radar={}, nbbo_rows=[q('SPY260904P00700000', 100, .3, '2026-09-04T11:58:00Z')], now_et=NOW)
    assert next(x for x in stale['theses'] if x['symbol'] == 'SPY')['direction'] == 'NO_BIAS'
