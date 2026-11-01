from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from scripts import build_b_select_core_v2_status as status
from trend_scanner.data.market_calendar import MarketCalendarAuthority
from trend_scanner.strategies import b_select_core_v2 as strategy


def _calendar():
    days = ['2026-09-30', '2026-10-28', '2026-10-29', '2026-10-30']
    return MarketCalendarAuthority.from_dates(days, completed_month_ends=['2026-09-30', '2026-10-30'])


def _stale_report():
    return {
        'identity': {'ticker': '123456', 'isu_cd': 'KR7123456000', 'name': 'Fixture', 'market': 'KOSDAQ', 'asset_type': 'COMMON'},
        'pattern': {'official_stage': 'PROGRESSED', 'history_12m': [
            {'as_of': '2026-09-30', 'stage': 'PROGRESSED', 'data_available': True},
            {'as_of': '2026-10-30', 'stage': 'UNAVAILABLE', 'data_available': False},
        ]},
    }


def test_missing_ticker_session_does_not_evaluate_stale_pattern_b(monkeypatch):
    calendar = _calendar()
    days = [str(day)[:10] for day in calendar.trading_dates]
    daily = pd.DataFrame({'close': [100.0]}, index=pd.to_datetime(['2026-10-28']))
    called = []
    monkeypatch.setattr(status, '_cached_rolling_production_market_calendar', lambda _root: calendar)
    monkeypatch.setattr(status.pattern_b_operational, 'history_chain', lambda *args: object())
    monkeypatch.setattr(status.pattern_b_operational, 'load_history', lambda *args: daily)
    monkeypatch.setattr(status, 'evaluate_pattern_b', lambda *args, **kwargs: called.append(args) or SimpleNamespace(
        pattern_b_state='NORMAL', evaluation_status=SimpleNamespace(value='READY')))
    identity = {'ticker': '123456', 'isu_cd': 'KR7123456000', 'effective_from': '2020-01-01', 'effective_to': '2026-10-30'}
    interval = {**identity, 'state': 'COMMON', 'market': 'KOSDAQ'}
    contexts = status._build_exact_session_contexts(
        root=Path('.'), ticker='123456', name='Fixture', identity=identity,
        intervals=[interval], trading_dates=days,
        session_dates=['2026-10-29', '2026-10-30'], report_pattern_history=[],
        repository=object(), pattern_a_evaluation_dates=set(),
    )
    assert called == []
    assert [row['pattern_b_state'] for row in contexts] == [None, None]
    assert [row['pattern_b_evaluation_status'] for row in contexts] == ['UNAVAILABLE', 'UNAVAILABLE']
    assert all(row['exact_session_observed'] is False for row in contexts)


def test_stale_progressed_is_not_today_stage_and_does_not_rewrite_history():
    report = _stale_report()
    original = [dict(row) for row in report['pattern']['history_12m']]
    result = status._report_previous_stage(
        report, reference_market_date='2026-10-30', trading_dates=['2026-09-30', '2026-10-30'],
        root=Path('.'), identity={'ticker': '123456', 'effective_from': '2020-01-01'},
        resolve_full_history=False, exact_session_observed=False,
        monthly_unavailability_reason='NO_EXACT_MARKET_MONTH_END_OBSERVATION',
    )
    assert result == ('UNAVAILABLE', None, None)
    assert report['pattern']['official_stage'] == 'PROGRESSED'
    assert report['pattern']['history_12m'] == original


def test_present_nonprogressed_current_stage_still_rejects_same_day_disagreement():
    report = {'pattern': {'official_stage': 'WEAK', 'history_12m': [
        {'as_of': '2026-10-30', 'stage': 'TRANSITION', 'data_available': True}]}}
    with pytest.raises(status.BSelectStatusError, match='CURRENT_STAGE_MISMATCH'):
        status._report_previous_stage(
            report, reference_market_date='2026-10-30', trading_dates=['2026-10-30'],
            root=Path('.'), identity={'ticker': '123456', 'effective_from': '2020-01-01'},
            resolve_full_history=False,
        )


def test_missing_session_exception_requires_the_exact_unavailable_reason():
    with pytest.raises(status.BSelectStatusError, match='UNAVAILABLE'):
        status._report_previous_stage(
            _stale_report(), reference_market_date='2026-10-30',
            trading_dates=['2026-09-30', '2026-10-30'], root=Path('.'),
            identity={'ticker': '123456', 'effective_from': '2020-01-01'},
            resolve_full_history=False, exact_session_observed=False,
            monthly_unavailability_reason='EVALUATOR_EXECUTION_FAILED',
        )


def test_prior_pending_survives_explicit_nonobservation_then_fills_once():
    pending = {'kind': 'ENTRY', 'signal_date': '2026-09-30', 'execution_date': None,
               'sequence': 1, 'strategy_id': strategy.STRATEGY_ID}
    first = status._replay_with_unobserved_pending(
        [], [], trading_dates=['2026-09-30', '2026-10-01'], exact_opens={},
        reference_market_date='2026-10-01', initial_pending=pending,
        execution_by_signal_date={'2026-09-30': None},
        unobserved_sessions={'2026-10-01'},
    )
    assert first['position'] is None and first['completed_trades'] == []
    assert first['pending']['execution_date'] is None
    second = status._replay_with_unobserved_pending(
        [{'date': '2026-10-02', 'state': 'DEPRESSED'}], [],
        trading_dates=['2026-09-30', '2026-10-01', '2026-10-02'],
        exact_opens={'2026-10-02': 100.0}, reference_market_date='2026-10-02',
        initial_pending=first['pending'], execution_by_signal_date={'2026-09-30': '2026-10-02'},
        unobserved_sessions={'2026-10-01'},
    )
    assert second['pending'] is None
    assert second['position']['entry_execution_date'] == '2026-10-02'
    assert second['position']['entry_open'] == 100.0
    assert second['completed_trades'] == []


def _source_and_view(tmp_path, *, exact=False, reason='NO_EXACT_MARKET_MONTH_END_OBSERVATION'):
    import json
    ticker = '123456'
    ref = '2026-10-30'
    old = '2026-10-28'
    rel = Path('artifacts/reporting/stock_reports/20261101/json/123456_fixture.json')
    source_path = tmp_path / rel
    source_path.parent.mkdir(parents=True)
    stage = 'PROGRESSED' if exact else 'UNAVAILABLE'
    observation = {'as_of': ref, 'stage': stage, 'data_available': exact,
                   'score': 65.0 if exact else None,
                   'candidate_state': 'candidate' if exact else 'insufficient_data',
                   'reason': None if exact else reason}
    source = {
        'ticker': ticker, 'market': 'KOSDAQ', 'asset_type': 'COMMON',
        'requested_as_of': '2026-11-01', 'reference_market_date': ref,
        'header': {'effective_as_of': ref if exact else old, 'cache_last_date': ref if exact else old},
        'current_snapshot': {'official_stage': 'PROGRESSED'},
        'monthly_history': {'full_monthly_history': [observation]},
    }
    source_path.write_text(json.dumps(source), encoding='utf-8')
    report = _stale_report()
    if exact:
        report['pattern']['history_12m'][-1] = {'as_of': ref, 'stage': 'PROGRESSED', 'data_available': True, 'score': 65.0}
    report['price_trend'] = {'price_status': 'AVAILABLE' if exact else 'UNAVAILABLE',
                             'latest_close_as_of': ref if exact else None,
                             'latest_close': 101.0 if exact else None}
    report['technical_details'] = {'requested_as_of': '2026-11-01', 'reference_market_date': ref,
                                   'price_status': 'AVAILABLE' if exact else 'UNAVAILABLE',
                                   'price_as_of': ref if exact else None,
                                   'data_quality': {'cache_last_date': ref if exact else old},
                                   'source_report': str(rel)}
    identity = {'ticker': ticker, 'isu_cd': 'KR7123456000', 'market': 'KOSDAQ', 'effective_from': '2020-01-01'}
    frame = pd.DataFrame({'open': [100.0], 'high': [101.0], 'low': [99.0], 'close': [101.0],
                          'volume': [500.0], 'trading_value': [50000.0]},
                         index=pd.to_datetime([ref if exact else old]))
    frame.attrs['session_projection_audit'] = {
        'projected_date_set_exact_match': True, 'silent_inner_drop_count': 0,
        'unexplained_adjusted_only_dates': [], 'rejected_raw_only_dates': [],
    }
    class Repo:
        def get_daily(self, ticker, start, end):
            assert ticker == '123456' and end == '2026-10-30'
            return frame
    return report, identity, Repo(), source_path


def test_report_freshness_uses_validated_ticker_identity_and_quote(tmp_path):
    report, identity, repo, _ = _source_and_view(tmp_path)
    assert status._validate_report_exact_session(
        report, root=tmp_path, identity=identity, repository=repo,
        target_as_of='2026-11-01', reference_market_date='2026-10-30',
        is_market_month_end=True,
    ) is False


@pytest.mark.parametrize('kind', ['identity', 'reason', 'contradictory_history', 'future_bar',
                                 'source_mismatch', 'projection_mismatch', 'authority_error', 'duplicate_monthly'])
def test_report_freshness_rejects_ambiguous_or_conflicting_evidence(tmp_path, kind):
    import json
    report, identity, repo, source_path = _source_and_view(tmp_path)
    if kind == 'identity':
        report['identity']['isu_cd'] = 'KR7999999000'
    elif kind == 'reason':
        source = json.loads(source_path.read_text());source['monthly_history']['full_monthly_history'][0]['reason'] = 'EVALUATOR_FAILED';source_path.write_text(json.dumps(source))
    elif kind == 'contradictory_history':
        source = json.loads(source_path.read_text());source['monthly_history']['full_monthly_history'][0]['data_available'] = True;source_path.write_text(json.dumps(source))
    elif kind == 'future_bar':
        original = repo.get_daily
        def future(*args):
            result = original(*args);result.index = pd.to_datetime(['2026-11-02']);return result
        repo.get_daily = future
    elif kind == 'projection_mismatch':
        original = repo.get_daily
        def mismatch(*args):
            result = original(*args);result.attrs['session_projection_audit']['projected_date_set_exact_match'] = False;return result
        repo.get_daily = mismatch
    elif kind == 'authority_error':
        def authority_error(*args):
            raise ValueError('raw/adjusted authority mismatch')
        repo.get_daily = authority_error
    elif kind == 'duplicate_monthly':
        source = json.loads(source_path.read_text());source['monthly_history']['full_monthly_history'].append(dict(source['monthly_history']['full_monthly_history'][0]));source_path.write_text(json.dumps(source))
    else:
        report['technical_details']['source_report'] = '../outside.json'
    with pytest.raises(status.BSelectStatusError):
        status._validate_report_exact_session(
            report, root=tmp_path, identity=identity, repository=repo,
            target_as_of='2026-11-01', reference_market_date='2026-10-30',
            is_market_month_end=True,
        )


@pytest.mark.parametrize('score', [0.0, 27.28])
def test_numeric_score_with_unavailable_stage_is_not_entry_or_error(tmp_path, score):
    import json
    report, identity, repo, source_path = _source_and_view(tmp_path, exact=True)
    source = json.loads(source_path.read_text())
    source['current_snapshot']['official_stage'] = 'UNAVAILABLE'
    source['monthly_history']['full_monthly_history'][0].update(
        score=score, stage='UNAVAILABLE', data_available=True, candidate_state='insufficient_data')
    source_path.write_text(json.dumps(source))
    report['pattern']['official_stage'] = 'UNAVAILABLE'
    report['pattern']['history_12m'][-1].update(
        score=score, stage='UNAVAILABLE', data_available=True, candidate_state='insufficient_data')
    assert status._validate_report_exact_session(
        report, root=tmp_path, identity=identity, repository=repo,
        target_as_of='2026-11-01', reference_market_date='2026-10-30',
        is_market_month_end=True,
    ) is True
    current, previous, _ = status._report_previous_stage(
        report, reference_market_date='2026-10-30', trading_dates=['2026-09-30', '2026-10-30'],
        root=tmp_path, identity=identity, resolve_full_history=False,
    )
    assert current == 'UNAVAILABLE' and previous is None
    assert strategy.is_entry_signal('DEPRESSED', current, 'TRANSITION') is False


@pytest.mark.parametrize(('score', 'available'), [(None, True), (0.0, False)])
def test_score_availability_contradiction_still_fails(tmp_path, score, available):
    import json
    report, identity, repo, source_path = _source_and_view(tmp_path, exact=True)
    source = json.loads(source_path.read_text())
    source['monthly_history']['full_monthly_history'][0].update(score=score, data_available=available)
    source_path.write_text(json.dumps(source))
    with pytest.raises(status.BSelectStatusError):
        status._validate_report_exact_session(
            report, root=tmp_path, identity=identity, repository=repo,
            target_as_of='2026-11-01', reference_market_date='2026-10-30', is_market_month_end=True,
        )


def test_valid_normal_exit_does_not_require_available_pattern_a(monkeypatch):
    calendar = _calendar()
    days = [str(day)[:10] for day in calendar.trading_dates]
    daily = pd.DataFrame({'close': [101.0]}, index=pd.to_datetime(['2026-10-30']))
    monkeypatch.setattr(status, '_cached_rolling_production_market_calendar', lambda _root: calendar)
    monkeypatch.setattr(status.pattern_b_operational, 'history_chain', lambda *args: object())
    monkeypatch.setattr(status.pattern_b_operational, 'load_history', lambda *args: daily)
    monkeypatch.setattr(status, 'evaluate_pattern_b', lambda *args, **kwargs: SimpleNamespace(
        pattern_b_state='NORMAL', evaluation_status=SimpleNamespace(value='READY')))
    class Loader:
        def __init__(self, *args, **kwargs): pass
        def load(self, ticker): return daily
    monkeypatch.setattr(status, 'RepositoryV2DailyLoader', Loader)
    monkeypatch.setattr(status, 'build_precomputed_ticker_context', lambda *args: object())
    monkeypatch.setattr(status, 'build_historical_snapshot_from_context', lambda *args, **kwargs: object())
    monkeypatch.setattr(status, 'evaluate_pattern_a', lambda _: SimpleNamespace(lifecycle_stage=None))
    identity = {'ticker': '123456', 'isu_cd': 'KR7123456000', 'effective_from': '2020-01-01', 'effective_to': '2026-10-30'}
    contexts = status._build_exact_session_contexts(
        root=Path('.'), ticker='123456', name='Fixture', identity=identity,
        intervals=[{**identity, 'state': 'COMMON', 'market': 'KOSDAQ'}], trading_dates=days,
        session_dates=['2026-10-30'], report_pattern_history=[], repository=object(),
    )
    assert contexts[0]['pattern_a_stage'] == 'UNAVAILABLE'
    assert contexts[0]['pattern_b_state'] == 'NORMAL'
    position = {'trade_sequence': 1, 'entry_signal_date': '2026-09-30',
                'entry_execution_date': '2026-10-28', 'entry_open': 100.0,
                'strategy_id': strategy.STRATEGY_ID}
    result = strategy.replay_lifecycle(
        [{'date': contexts[0]['date'], 'state': contexts[0]['pattern_b_state']}], [],
        trading_dates=days, exact_opens={}, reference_market_date='2026-10-30',
        initial_position=position, certified_through='2026-11-01',
    )
    assert result['pending']['kind'] == 'EXIT'
    assert result['pending']['execution_date'] is None
    assert result['position'] is not None and result['completed_trades'] == []


def test_unresolved_pending_requires_proven_unobserved_sessions():
    pending = {'kind': 'ENTRY', 'signal_date': '2026-09-30', 'execution_date': None,
               'sequence': 1, 'strategy_id': strategy.STRATEGY_ID}
    with pytest.raises(status.BSelectStatusError, match='UNOBSERVED_SESSION_EVIDENCE_INVALID'):
        status._replay_with_unobserved_pending(
            [], [], trading_dates=['2026-09-30', '2026-10-01'], exact_opens={},
            reference_market_date='2026-10-01', initial_pending=pending,
            execution_by_signal_date={'2026-09-30': None}, unobserved_sessions=set(),
        )


def test_unobserved_exit_pending_keeps_original_open_trade():
    position = {'trade_sequence': 2, 'entry_signal_date': '2026-08-31',
                'entry_execution_date': '2026-09-01', 'entry_open': 100.0,
                'strategy_id': strategy.STRATEGY_ID}
    pending = {'kind': 'EXIT', 'signal_date': '2026-09-30', 'execution_date': None,
               'sequence': 2, 'strategy_id': strategy.STRATEGY_ID}
    result = status._replay_with_unobserved_pending(
        [], [], trading_dates=['2026-09-30', '2026-10-01'], exact_opens={},
        reference_market_date='2026-10-01', initial_position=position, initial_pending=pending,
        execution_by_signal_date={'2026-09-30': None}, unobserved_sessions={'2026-10-01'},
    )
    assert result['position']['trade_sequence'] == 2
    assert result['position']['entry_open'] == 100.0
    assert result['pending']['execution_date'] is None
    assert result['completed_trades'] == []


def test_first_valid_open_schedule_skips_absent_bar_but_rejects_invalid_open(monkeypatch):
    days = ['2026-09-30', '2026-10-01', '2026-10-02']
    frame = pd.DataFrame({'open': [100.0, 120.0]},
                         index=pd.to_datetime(['2026-09-30', '2026-10-02']))
    class Loader:
        def __init__(self, *args, **kwargs): pass
        def load(self, ticker): return frame
    monkeypatch.setattr(status, 'RepositoryV2DailyLoader', Loader)
    intervals = [{'ticker': '123456', 'isu_cd': 'KR7123456000', 'state': 'COMMON',
                  'effective_from': '2020-01-01', 'effective_to': '2026-10-02'}]
    kwargs = dict(repository=object(), ticker='123456', isu_cd='KR7123456000',
                  signal_dates={'2026-09-30'}, intervals=intervals,
                  trading_dates=days, reference_market_date='2026-10-02')
    opens, schedule = status._first_valid_open_schedule(**kwargs)
    assert opens == {'2026-10-02': 120.0}
    assert schedule == {'2026-09-30': '2026-10-02'}
    frame.loc[pd.Timestamp('2026-10-02'), 'open'] = 0.0
    with pytest.raises(status.BSelectStatusError, match='OBSERVED_VALID_OPEN_UNAVAILABLE'):
        status._first_valid_open_schedule(**kwargs)
