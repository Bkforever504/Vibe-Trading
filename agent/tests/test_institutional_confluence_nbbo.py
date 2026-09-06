from datetime import datetime, timezone
from scripts import institutional_confluence_shadow as module

NOW = datetime(2026, 9, 4, 14, 0, 30, tzinfo=timezone.utc)


def event(direction='LONG'):
    return {'symbol': 'SPY', 'direction': direction, 'state': 'CONFIRMED', 'bar_completed_at': '2026-09-04T14:00:30Z'}


def quote(right, size, iv):
    return {'symbol': f'SPY260904{right}00700000', 'bid': 1, 'ask': 1.2, 'ask_size': size, 'iv': iv,
            'quote_timestamp': '2026-09-04T14:00:00Z', 'quote_scope': 'databento_opra_cbbo_1s',
            'provenance': {'provider': 'databento', 'licensed_consolidated_nbbo': True}}


def test_nbbo_short_flow_vetoes_long_candidate():
    report = module.build_report(as_of=NOW, alerts={'recent_events': [event()]}, gex_rows=[], czt={},
                                 nbbo_rows=[quote('P', 100, .3), quote('C', 10, .2)])
    card = report['cards'][0]
    nbbo = next(x for x in card['sources'] if x['name'] == 'nbbo_options_flow')
    assert nbbo['available'] is True and nbbo['fresh'] is True
    assert nbbo['contradicts_candidate'] is True
    assert card['recommendation'] == 'contradiction_observed'


def test_two_explicit_directional_sources_can_establish_confluence():
    report = module.build_report(as_of=NOW, alerts={'recent_events': [event('SHORT')]}, czt={},
        gex_rows=[{'timestamp': '2026-09-04T14:00:00Z', 'scans': [{'symbol': 'SPY', 'status': 'ok', 'gex_wall': {'strike': 700}, 'direction': 'SHORT'}]}],
        nbbo_rows=[quote('P', 100, .3), quote('C', 10, .2)])
    card = report['cards'][0]
    assert card['independent_sources_available'] == 2
    assert card['independent_sources_aligned'] == 2
    assert card['recommendation'] == 'confluence_observed'


def test_stale_nbbo_is_unavailable_and_neutral():
    stale = [{**quote('P', 100, .3), 'quote_timestamp': '2026-09-04T13:58:00Z'}]
    card = module.build_report(as_of=NOW, alerts={'recent_events': [event()]}, gex_rows=[], czt={}, nbbo_rows=stale)['cards'][0]
    nbbo = next(x for x in card['sources'] if x['name'] == 'nbbo_options_flow')
    assert nbbo['available'] is False and nbbo['direction'] == 'NEUTRAL'
