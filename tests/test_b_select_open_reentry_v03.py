from __future__ import annotations

from copy import deepcopy
import inspect
from pathlib import Path

import pandas as pd
import pytest

from scripts import build_b_select_core_v2_status as status
from scripts import run_pattern_b_pure_simple_backtest_v01 as source


TICKER = '123456'
ISU = 'KR7123456000'
COMPONENT = f'{TICKER}:{ISU}:000'
DAYS = ['2026-08-31', '2026-09-01', '2026-09-28', '2026-09-29', '2026-09-30',
        '2026-10-01', '2026-10-02', '2026-10-06', '2026-10-07', '2026-10-08']


def _open_trade():
    return {'ticker': TICKER, 'isu_cd': ISU, 'name': 'fixture', 'market': 'KOSDAQ',
            'asset_type': 'COMMON', 'trade_sequence': 2, 'entry_signal_date': '2026-09-30',
            'entry_execution_date': '2026-10-01', 'entry_open': 100.0,
            'exit_signal_date': None, 'exit_execution_date': None, 'exit_price': None,
            'exit_reason': None, 'trade_status': 'OPEN_AT_REFERENCE', 'return_pct': 5.0,
            'strategy_id': status.STRATEGY_ID}


def _realized_trade():
    return {**_open_trade(), 'trade_sequence': 1, 'entry_signal_date': '2026-08-31',
            'entry_execution_date': '2026-09-01', 'entry_open': 80.0,
            'exit_signal_date': '2026-09-28', 'exit_execution_date': '2026-09-29',
            'exit_price': 88.0, 'exit_reason': 'PATTERN_B_NORMAL_NEXT_OPEN',
            'trade_status': 'REALIZED', 'return_pct': 10.0, 'exit_strategy_id': status.STRATEGY_ID}


def _prior():
    trade = _open_trade()
    return {'strategy_id': status.STRATEGY_ID, 'reference_market_date': '2026-10-02',
            'items': [], 'canonical_trade_history': [_realized_trade(), trade],
            'canonical_trade_history_row_count': 2,
            'canonical_current_open_positions': [dict(trade)], 'canonical_current_open_position_count': 1,
            'canonical_pending_events': [], 'canonical_pending_event_count': 0,
            'catchup_audit': {'catchup_session_dates': [], 'recovered_month_end_dates': []},
            'catchup_entry_pattern_a_authorities': []}


def _authority():
    interval = {'ticker': TICKER, 'isu_cd': ISU, 'state': 'COMMON', 'market': 'KOSDAQ',
                'effective_from': '2020-01-01', 'effective_to': '2026-10-08'}
    identity = {'ticker': TICKER, 'isu_cd': ISU, 'market': 'KOSDAQ', 'component_id': COMPONENT,
                'effective_from': interval['effective_from'], 'effective_to': interval['effective_to']}
    candidate = {'ticker': TICKER, 'isu_cd': ISU, 'component_id': COMPONENT,
                 'entry_signal_date': '2026-09-30', 'entry_pattern_a_stage_recomputed': 'PROGRESSED',
                 'previous_pattern_a_stage': 'EARLY_TREND', 'previous_pattern_a_stage_date': '2026-08-31',
                 'entry_pattern_a_lookahead_free': True}
    return identity, [interval], {source.interval_key(interval): COMPONENT}, [candidate]


def _seed(prior, identity=None, intervals=None, components=None, candidates=None):
    original_identity, original_intervals, original_components, original_candidates = _authority()
    opens = status._validated_prior_canonical_opens(prior)
    return status._build_reentry_prior_item(
        prior_status=prior, prior_open=opens[(TICKER, ISU)], identity=identity or original_identity,
        intervals=original_intervals if intervals is None else intervals,
        interval_components=original_components if components is None else components,
        trading_dates=DAYS, prior_reference_market_date='2026-10-02',
        reference_market_date='2026-10-08', candidate_rows=original_candidates if candidates is None else candidates,
    )


def test_real_prior_open_loss_diagnostic_identifies_trade_key():
    prior = status._read_json(status.ROOT / 'artifacts/strategies/b_select_core_v2/production/20261024/status.json')
    old = [t for t in prior['canonical_trade_history'] if t['trade_status'] == 'OPEN_AT_REFERENCE']
    actual = next(t for t in old if t['ticker'] == '156100')
    assert not any(x['ticker'] == '156100' and x['isu_cd'] == actual['isu_cd'] for x in prior['items'])
    with pytest.raises(status.BSelectStatusError, match=r'OPEN_ROW_LOST.*156100.*KR7156100000.*1.*2026-04-30.*2026-05-04'):
        status._merge_incremental_canonical_history(
            prior_rows=prior['canonical_trade_history'], current_rows=[x for x in old if x is not actual],
            hidden_open_updates={}, current_identity_pairs={(x['ticker'], x['isu_cd']) for x in old},
            prior_reference_market_date='2026-10-23', reference_market_date='2026-10-30',
            trading_dates=['2026-10-23', '2026-10-26', '2026-10-27', '2026-10-28', '2026-10-29', '2026-10-30'])


def test_first_valid_open_after_unobserved_session_is_accepted_only_with_authority(monkeypatch):
    days = ['2026-09-30', '2026-10-01', '2026-10-02', '2026-10-06', '2026-10-07', '2026-10-08']
    frame = pd.DataFrame({'open': [100.0, 110.0]}, index=pd.to_datetime(['2026-10-06', '2026-10-08']))
    class Loader:
        def __init__(self, *args, **kwargs): pass
        def load(self, ticker): return frame
    monkeypatch.setattr(status, 'RepositoryV2DailyLoader', Loader)
    interval = _authority()[1][0]
    opens, schedule = status._first_valid_open_schedule(
        repository=object(), ticker=TICKER, isu_cd=ISU, signal_dates={'2026-10-06'},
        intervals=[interval], trading_dates=days, reference_market_date='2026-10-08')
    assert opens == {'2026-10-08': 110.0} and schedule == {'2026-10-06': '2026-10-08'}
    opened = _open_trade()
    realized = {**opened, 'trade_status': 'REALIZED', 'exit_signal_date': '2026-10-06',
                'exit_execution_date': '2026-10-08', 'exit_price': 110.0,
                'exit_reason': 'PATTERN_B_NORMAL_NEXT_OPEN', 'return_pct': 10.0,
                'exit_strategy_id': status.STRATEGY_ID}
    kwargs = dict(prior_rows=[opened], current_rows=[realized], hidden_open_updates={},
                  current_identity_pairs={(TICKER, ISU)}, prior_reference_market_date='2026-10-02',
                  reference_market_date='2026-10-08', trading_dates=days)
    if 'repository' in inspect.signature(status._merge_incremental_canonical_history).parameters:
        kwargs.update(repository=object(), intervals=[interval])
    merged, count = status._merge_incremental_canonical_history(**kwargs)
    assert merged == [realized] and count == 1


def test_reentry_restores_identical_open_and_prior_realized_without_new_entry():
    prior = _prior(); seed = _seed(prior)
    assert seed['canonical_position'] == 'OPEN'
    assert seed['current_trade']['entry_open'] == 100.0
    assert seed['current_trade']['trade_sequence'] == 2
    assert seed['current_trade']['entry_signal_date'] == '2026-09-30'
    assert seed['trade_history'] == prior['canonical_trade_history']
    assert seed['entry_pattern_a_stage'] == 'PROGRESSED'
    assert seed['entry_previous_pattern_a_stage'] == 'EARLY_TREND'
    lifecycle = status._replay_with_unobserved_pending(
        [{'date': day, 'state': 'DEPRESSED'} for day in DAYS[-3:]], [], trading_dates=DAYS,
        exact_opens={}, reference_market_date='2026-10-08', initial_position=seed['current_trade'],
        initial_trade_sequence=2, execution_by_signal_date={})
    assert lifecycle['position']['trade_sequence'] == 2
    assert lifecycle['completed_trades'] == [] and lifecycle['pending'] is None


@pytest.mark.skipif(
    not all((status.ROOT / path).is_file() for path in (source.PIT_PATH, source.CALENDAR_PATH)),
    reason='local rolling PIT/calendar authorities are not installed',
)
def test_real_156100_uses_saved_open_and_qualified_entry_authority():
    root = status.ROOT
    prior = status._read_json(root / 'artifacts/strategies/b_select_core_v2/production/20261024/status.json')
    intervals, days, _ = source._load_authorities(root)
    components, _ = source._interval_components(intervals, days)
    identity = {**status._current_identity_map(intervals, components, '2026-10-30')['156100'], 'ticker': '156100'}
    candidates = status._rebind_candidate_components(status._load_candidate_signals(root), intervals, components, {'156100'})
    opened = status._validated_prior_canonical_opens(prior)[('156100', 'KR7156100000')]
    seed = status._build_reentry_prior_item(
        prior_status=prior, prior_open=opened, identity=identity, intervals=intervals, interval_components=components,
        trading_dates=days, prior_reference_market_date='2026-10-23', reference_market_date='2026-10-30',
        candidate_rows=candidates)
    assert seed['current_trade']['entry_open'] == 7320.0
    assert seed['current_trade']['entry_signal_date'] == '2026-04-30'
    assert seed['current_trade']['entry_execution_date'] == '2026-05-04'
    assert seed['entry_pattern_a_stage'] == 'PROGRESSED'
    assert seed['entry_previous_pattern_a_stage'] == 'EARLY_TREND'


@pytest.mark.parametrize('change', ['duplicate_ledger', 'duplicate_open_list', 'changed_open_list',
                                    'invalid_strategy', 'visible_flat', 'visible_mismatch'])
def test_prior_canonical_contradictions_fail_closed(change):
    prior = _prior()
    if change == 'duplicate_ledger': prior['canonical_trade_history'].append(deepcopy(prior['canonical_trade_history'][-1]));prior['canonical_trade_history_row_count'] += 1
    if change == 'duplicate_open_list': prior['canonical_current_open_positions'].append(deepcopy(prior['canonical_current_open_positions'][0]));prior['canonical_current_open_position_count'] += 1
    if change == 'changed_open_list': prior['canonical_current_open_positions'][0]['entry_open'] = 101.0
    if change == 'invalid_strategy': prior['canonical_trade_history'][-1]['strategy_id'] = 'WRONG'
    if change in {'visible_flat', 'visible_mismatch'}:
        trade = deepcopy(prior['canonical_trade_history'][-1]); item = {'ticker':TICKER,'isu_cd':ISU,
            'canonical_position':'FLAT' if change == 'visible_flat' else 'OPEN','current_trade':trade,
            'trade_history':[trade], 'pending_event':None}
        if change == 'visible_mismatch': item['current_trade']['entry_open'] = 101.0
        prior['items'].append(item)
    with pytest.raises(status.BSelectStatusError): status._validated_prior_canonical_opens(prior)


@pytest.mark.parametrize('change', ['wrong_isu', 'wrong_component', 'missing_entry_interval', 'missing_authority', 'duplicate_authority'])
def test_reentry_rejects_ambiguous_identity_and_missing_entry_evidence(change):
    prior = _prior(); identity, intervals, components, candidates = _authority()
    if change == 'wrong_isu': identity['isu_cd'] = 'KR7999999000'
    if change == 'wrong_component': identity['component_id'] = 'DIFFERENT'
    if change == 'missing_entry_interval': intervals[0]['effective_from'] = '2026-10-02';components = {source.interval_key(intervals[0]): COMPONENT}
    if change == 'missing_authority': candidates = []
    if change == 'duplicate_authority': candidates.append(dict(candidates[0]))
    with pytest.raises(status.BSelectStatusError):
        _seed(prior, identity=identity, intervals=intervals, components=components, candidates=candidates)


def test_reentry_preserves_canonical_prior_exit_pending_without_future_fill():
    prior = _prior(); row = prior['canonical_trade_history'][-1]; row['exit_signal_date'] = '2026-10-02'
    prior['canonical_current_open_positions'][0]['exit_signal_date'] = '2026-10-02'
    event = {'ticker': TICKER, 'isu_cd': ISU, 'kind': 'EXIT', 'signal_date': '2026-10-02',
             'execution_date': None, 'trade_sequence': 2, 'strategy_id': status.STRATEGY_ID}
    prior['canonical_pending_events'] = [event]; prior['canonical_pending_event_count'] = 1
    seed = _seed(prior)
    assert seed['pending_event'] == event
    assert seed['pending_event']['execution_date'] is None


def test_hidden_open_never_has_both_current_and_hidden_updates():
    trade = _open_trade(); key = status._canonical_trade_key(trade)
    with pytest.raises(status.BSelectStatusError, match='HIDDEN_OPEN_UPDATE_SET_MISMATCH'):
        status._merge_incremental_canonical_history(
            prior_rows=[trade], current_rows=[trade], hidden_open_updates={key:trade},
            current_identity_pairs={(TICKER, ISU)}, prior_reference_market_date='2026-10-02',
            reference_market_date='2026-10-08', trading_dates=DAYS)


def test_delayed_execution_cannot_be_assumed_without_price_authority():
    trade = _open_trade()
    realized = {**trade, 'trade_status': 'REALIZED', 'exit_signal_date': '2026-10-06',
                'exit_execution_date': '2026-10-08', 'exit_price': 110.0,
                'exit_reason': 'PATTERN_B_NORMAL_NEXT_OPEN', 'return_pct': 10.0,
                'exit_strategy_id': status.STRATEGY_ID}
    with pytest.raises(status.BSelectStatusError, match='ILLEGAL_OPEN_TO_REALIZED'):
        status._merge_incremental_canonical_history(
            prior_rows=[trade], current_rows=[realized], hidden_open_updates={},
            current_identity_pairs={(TICKER, ISU)}, prior_reference_market_date='2026-10-02',
            reference_market_date='2026-10-08', trading_dates=DAYS)


def test_delayed_execution_rejects_wrong_price_or_skipping_an_observed_open(monkeypatch):
    frame = pd.DataFrame({'open': [100.0, 110.0]}, index=pd.to_datetime(['2026-10-06', '2026-10-08']))
    class Loader:
        def __init__(self, *args, **kwargs): pass
        def load(self, ticker): return frame
    monkeypatch.setattr(status, 'RepositoryV2DailyLoader', Loader)
    trade = _open_trade()
    realized = {**trade, 'trade_status': 'REALIZED', 'exit_signal_date': '2026-10-06',
                'exit_execution_date': '2026-10-08', 'exit_price': 111.0,
                'exit_reason': 'PATTERN_B_NORMAL_NEXT_OPEN', 'return_pct': 11.0,
                'exit_strategy_id': status.STRATEGY_ID}
    kwargs = dict(prior_rows=[trade], current_rows=[realized], hidden_open_updates={},
                  current_identity_pairs={(TICKER, ISU)}, prior_reference_market_date='2026-10-02',
                  reference_market_date='2026-10-08', trading_dates=DAYS,
                  repository=object(), intervals=_authority()[1])
    with pytest.raises(status.BSelectStatusError, match='ILLEGAL_OPEN_TO_REALIZED'):
        status._merge_incremental_canonical_history(**kwargs)
    realized['exit_price'] = 110.0
    frame.loc[pd.Timestamp('2026-10-07'), 'open'] = 105.0
    frame.sort_index(inplace=True)
    with pytest.raises(status.BSelectStatusError, match='ILLEGAL_OPEN_TO_REALIZED'):
        status._merge_incremental_canonical_history(**kwargs)


@pytest.mark.skipif(
    not all((status.ROOT / path).is_file() for path in (source.PIT_PATH, source.CALENDAR_PATH))
    or not (status.ROOT / 'artifacts/reporting/stock_reports/20261101/json').is_dir(),
    reason='local exact-date PIT/calendar and stock report corpus are not installed',
)
def test_reentry_status_builder_integrates_real_identity_and_ledger(monkeypatch, tmp_path):
    from scripts import export_stock_report_web
    root = status.ROOT
    saved = status._read_json(root / 'artifacts/strategies/b_select_core_v2/production/20261024/status.json')
    trade = next(x for x in saved['canonical_trade_history']
                 if x['ticker'] == '156100' and x['trade_status'] == 'OPEN_AT_REFERENCE')
    prior = {**saved, 'items': [], 'canonical_trade_history': [trade],
             'canonical_trade_history_row_count': 1, 'canonical_current_open_positions': [dict(trade)],
             'canonical_current_open_position_count': 1, 'canonical_pending_events': [],
             'canonical_pending_event_count': 0, 'catchup_entry_pattern_a_authorities': []}
    monkeypatch.setattr(status, '_latest_prior_status', lambda *a, **k: (prior, 'fixture-prior-status'))
    index, reports, _ = export_stock_report_web.build_web_payload(
        root, target_as_of='2026-11-01', reference_market_date='2026-10-30', include_etf=False)
    index['items'] = [x for x in index['items'] if x.get('ticker') == '156100' and x.get('report_available')]
    assert len(index['items']) == 1
    stocks = tmp_path / 'stocks'; stocks.mkdir()
    (stocks / '156100.json').write_text(__import__('json').dumps(reports['156100'], ensure_ascii=False))
    index_path = tmp_path / 'stock-index.json'; index_path.write_text(__import__('json').dumps(index, ensure_ascii=False))
    result = status.build_b_select_status(repo_root=root, index_path=index_path, stocks_path=stocks,
                                          target_as_of='2026-11-01', reference_market_date='2026-10-30')
    prior_key = status._canonical_trade_key(trade)
    matches = [row for row in result['canonical_trade_history'] if status._canonical_trade_key(row) == prior_key]
    assert result['status'] == 'PASS' and len(matches) == 1
    assert matches[0]['trade_status'] in {'OPEN_AT_REFERENCE', 'REALIZED'}
    assert matches[0]['entry_open'] == trade['entry_open']
    item = result['items'][0]
    assert len([row for row in item['trade_history'] if row['trade_sequence'] == trade['trade_sequence']]) == 1


@pytest.mark.parametrize('change', ['invalid_signal_date', 'signal_after_prior_reference', 'execution_in_past'])
def test_prior_pending_dates_must_be_valid_before_reentry(change):
    prior = _prior()
    signal = {'invalid_signal_date':'2026-10-04', 'signal_after_prior_reference':'2026-10-06',
              'execution_in_past':'2026-10-02'}[change]
    prior['canonical_trade_history'][-1]['exit_signal_date'] = signal
    prior['canonical_current_open_positions'][0]['exit_signal_date'] = signal
    prior['canonical_pending_events'] = [{'ticker':TICKER,'isu_cd':ISU,'kind':'EXIT',
        'signal_date':signal,'execution_date':'2026-10-02' if change == 'execution_in_past' else None,
        'trade_sequence':2,'strategy_id':status.STRATEGY_ID}]
    prior['canonical_pending_event_count'] = 1
    with pytest.raises(status.BSelectStatusError): _seed(prior)


def test_visible_prior_pending_cannot_disagree_with_canonical_pending():
    prior = _prior(); trade = prior['canonical_trade_history'][-1]
    trade['exit_signal_date'] = '2026-10-02';prior['canonical_current_open_positions'][0]['exit_signal_date'] = '2026-10-02'
    prior['items'] = [{'ticker':TICKER,'isu_cd':ISU,'canonical_position':'OPEN',
                       'current_trade':dict(trade),'trade_history':[dict(trade)],'pending_event':None}]
    prior['canonical_pending_events'] = [{'ticker':TICKER,'isu_cd':ISU,'kind':'EXIT',
        'signal_date':'2026-10-02','execution_date':None,'trade_sequence':2,'strategy_id':status.STRATEGY_ID}]
    prior['canonical_pending_event_count'] = 1
    with pytest.raises(status.BSelectStatusError): status._validated_prior_canonical_opens(prior)


def test_reentry_rejects_noncanonical_open_and_future_predecessor_authority():
    prior = _prior();identity, intervals, components, candidates = _authority()
    bad_open = {**_open_trade(), 'entry_open': 101.0}
    kwargs = dict(prior_status=prior, prior_open=bad_open, identity=identity, intervals=intervals,
                  interval_components=components, trading_dates=DAYS, prior_reference_market_date='2026-10-02',
                  reference_market_date='2026-10-08', candidate_rows=candidates)
    with pytest.raises(status.BSelectStatusError): status._build_reentry_prior_item(**kwargs)
    kwargs['prior_open'] = _open_trade();candidates[0]['previous_pattern_a_stage_date'] = '2026-10-08'
    with pytest.raises(status.BSelectStatusError): status._build_reentry_prior_item(**kwargs)


def test_reentered_open_is_not_a_new_buy_when_an_entry_signal_occurs():
    seed = _seed(_prior())
    lifecycle = status._replay_with_unobserved_pending(
        [{'date':'2026-10-30','state':'DEPRESSED'}],
        [{'date':'2026-10-30','pattern_a_stage':'PROGRESSED','previous_pattern_a_stage':'EARLY_TREND'}],
        trading_dates=[*DAYS, '2026-10-30', '2026-11-02'], exact_opens={'2026-11-02':120.0},
        reference_market_date='2026-11-02',
        initial_position=seed['current_trade'], initial_trade_sequence=2,
        execution_by_signal_date={'2026-10-30':'2026-11-02'})
    assert lifecycle['position']['trade_sequence'] == 2
    assert lifecycle['position']['entry_open'] == 100.0
    assert lifecycle['completed_trades'] == [] and lifecycle['pending'] is None


def test_reentry_exit_pending_fills_once_at_first_observed_open():
    prior = _prior(); prior['canonical_trade_history'][-1]['exit_signal_date'] = '2026-10-02'
    prior['canonical_current_open_positions'][0]['exit_signal_date'] = '2026-10-02'
    prior['canonical_pending_events'] = [{'ticker':TICKER,'isu_cd':ISU,'kind':'EXIT',
        'signal_date':'2026-10-02','execution_date':None,'trade_sequence':2,'strategy_id':status.STRATEGY_ID}]
    prior['canonical_pending_event_count'] = 1; seed = _seed(prior); event = seed['pending_event']
    pending = {'kind':event['kind'],'signal_date':event['signal_date'],'execution_date':'2026-10-07',
               'sequence':event['trade_sequence'],'strategy_id':event['strategy_id']}
    lifecycle = status._replay_with_unobserved_pending(
        [{'date':'2026-10-07','state':'DEPRESSED'}, {'date':'2026-10-08','state':'DEPRESSED'}], [],
        trading_dates=DAYS, exact_opens={'2026-10-07':110.0,'2026-10-08':112.0},
        reference_market_date='2026-10-08', initial_position=seed['current_trade'], initial_pending=pending,
        initial_trade_sequence=2, execution_by_signal_date={'2026-10-02':'2026-10-07'},
        unobserved_sessions={'2026-10-06'})
    assert len(lifecycle['completed_trades']) == 1
    assert lifecycle['completed_trades'][0]['exit_execution_date'] == '2026-10-07'
    assert lifecycle['completed_trades'][0]['exit_price'] == 110.0
    assert lifecycle['position'] is None and lifecycle['pending'] is None


def test_current_published_identity_routes_match_the_same_date_canonical_status():
    from scripts.export_b_select_core_v2_identity_reports_web import validate_identity_routes
    root = status.ROOT
    health = status._read_json(root / 'web/data/health.json')
    date_key = str(health['requested_as_of']).replace('-', '')
    published = status._read_json(root / 'artifacts/strategies/b_select_core_v2/production' / date_key / 'status.json')
    actual = validate_identity_routes(root / 'web/data', published)
    assert actual['status'] == 'PASS'
    assert actual['route_count'] == actual['unique_exact_identity_count'] > 0
    assert actual['missing_route_count'] == actual['identity_mismatch_count'] == 0
