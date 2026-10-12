#!/usr/bin/env python3
from __future__ import annotations
import csv, hashlib, importlib.util, json, platform, sqlite3, subprocess, sys, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[5]
OUT=Path(__file__).resolve().parent
V01=ROOT/'artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p2_2_official_realistic_portfolio_v01'
P31=ROOT/'artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01'
P32=ROOT/'artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_realistic_v01'
W=Path('/Users/june/Documents/projects/w.md')

def sha(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()

def run():
    started=time.perf_counter()
    v01_manifest=json.loads((V01/'source_manifest.json').read_text())
    old_manifest=json.loads((V01/'source_manifest_pre_sample.json').read_text())
    preflight=json.loads((V01/'preflight.json').read_text())
    validation=json.loads((V01/'sample_validation.json').read_text())
    benchmark=json.loads((V01/'sample_benchmark.json').read_text())
    artifact_hashes=json.loads((V01/'artifact_hashes.json').read_text())
    branch=subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip()
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    origin=subprocess.check_output(['git','rev-parse','origin/main'],cwd=ROOT,text=True).strip()
    tracked_clean=(subprocess.call(['git','diff','--quiet'],cwd=ROOT)==0 and subprocess.call(['git','diff','--cached','--quiet'],cwd=ROOT)==0)

    final_match=[]; final_bad=[]; stale_directive=[]
    for row in v01_manifest['files']:
        p=Path(row.get('absolute_path') or row['path'])
        if not p.is_file():
            final_bad.append({'path':row['path'],'reason':'MISSING'})
        elif sha(p)==row.get('sha256') and p.stat().st_size==int(row.get('bytes',-1)):
            final_match.append(row['path'])
        elif row['path']=='/Users/june/Documents/projects/w.md':
            stale_directive.append({'previous_sha256':row['sha256'],'current_sha256':sha(p),'previous_bytes':row['bytes'],'current_bytes':p.stat().st_size})
        else:
            final_bad.append({'path':row['path'],'reason':'HASH_OR_SIZE_MISMATCH','actual_sha256':sha(p)})
    old_match=[]; old_diff=[]
    for row in old_manifest['files']:
        p=Path(row.get('absolute_path') or row['path'])
        actual=sha(p) if p.is_file() else None
        if actual==row.get('sha256') and p.stat().st_size==int(row.get('bytes',-1)):
            old_match.append(row['path'])
        else:
            old_diff.append(row['path'])

    artifact_match=[]; artifact_bad=[]
    for row in artifact_hashes['files']:
        p=V01/row['path']
        if p.is_file() and sha(p)==row['sha256'] and p.stat().st_size==int(row['bytes']):
            artifact_match.append(row['path'])
        else:
            artifact_bad.append(row['path'])

    p2_runner='artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p2_2_official_realistic_portfolio_v01/run_p2_2_replay.py'
    final_ref={x['path']:x for x in v01_manifest['files']}
    p32_source_manifest=json.loads((P32/'source_manifest.json').read_text())
    p32_ref={x['path']:x for x in p32_source_manifest['source_files']}
    required_code_match={}
    for rel in [
        p2_runner,
        'src/trend_scanner/universe/permanent_identity_exclusions.py',
        'src/trend_scanner/data/repository_v2.py',
        'src/trend_scanner/data/repository_v2_loader.py',
        'src/trend_scanner/validation/pattern_a_fast_core_v02_reentry.py',
        'scripts/evaluate_pattern_a_fast_core_v02_reentry.py',
        'artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01/run_official_realistic_replay.py',
    ]:
        rec=final_ref.get(rel) or p32_ref.get(rel); p=ROOT/rel
        required_code_match[rel]=bool(rec and p.is_file() and sha(p)==rec.get('sha256') and ('bytes' not in rec or p.stat().st_size==int(rec['bytes'])))

    with (V01/'identity_price_preflight.csv').open(newline='') as f:
        prices=list(csv.DictReader(f))
    adjusted_bad=[]
    for row in prices:
        p=ROOT/'data/market/adjusted/stocks'/f"{str(row['ticker']).zfill(6)}.parquet"
        if not p.is_file() or sha(p)!=row['adjusted_file_sha256']:
            adjusted_bad.append(row['ticker'])

    rawroot=ROOT/'data/market/raw/krx_stocks/v01'
    dbp=rawroot/'manifest.sqlite3'
    db=sqlite3.connect(f'file:{dbp.resolve()}?mode=ro',uri=True)
    current_manifest={(r[0],r[1]):r for r in db.execute('SELECT market,date,status,file_path,row_count,content_sha256,file_sha256 FROM raw_snapshot_manifest')}
    with (V01/'raw_partition_preflight.csv').open(newline='') as f:
        raw_rows=list(csv.DictReader(f))
    raw_bad=[]; raw_missing=[]
    for row in raw_rows:
        key=(row['market'],row['partition_date'])
        current=current_manifest.get(key)
        if current is None:
            raw_missing.append(key); continue
        market,day,status,relative_path,row_count,content_hash,file_hash=current
        p=Path(relative_path); p=p if p.is_absolute() else rawroot/p
        if (status!='COMPLETE' or int(row_count)!=int(row['row_count'])
            or content_hash!=row['content_sha256'] or file_hash!=row['file_sha256']
            or not p.is_file() or sha(p)!=row['file_sha256']):
            raw_bad.append({'key':key,'status':status,'path':str(p),'exists':p.is_file()})
    db_hash=sha(dbp)

    sys.path.insert(0,str(ROOT))
    from trend_scanner.universe.permanent_identity_exclusions import PERMANENT_IDENTITY_EXCLUSIONS
    pairs=sorted((str(t).zfill(6),str(i).strip().upper()) for t,i in PERMANENT_IDENTITY_EXCLUSIONS)
    canonical=hashlib.sha256(json.dumps({'schema':'sorted_exact_pair_json_v01','pairs':[list(x) for x in pairs]},ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    registry_sha=sha(ROOT/'src/trend_scanner/universe/permanent_identity_exclusions.py')

    engine_path=P31/'run_official_realistic_replay.py'
    spec=importlib.util.spec_from_file_location('p2_v02_reuse_authority_check',engine_path)
    engine=importlib.util.module_from_spec(spec); sys.modules[spec.name]=engine; spec.loader.exec_module(engine)
    engine.EVAL_START=pd.Timestamp('2021-01-04'); engine.CUTOFF=pd.Timestamp('2026-08-31'); engine.SUPPORT=pd.Timestamp('2026-09-01')
    calendar,pit_payload,calendar_payload,segments=engine.build_authority()
    all_dates=pd.DatetimeIndex(calendar.trading_dates).normalize()
    eval_dates=all_dates[(all_dates>=pd.Timestamp('2021-01-04'))&(all_dates<=pd.Timestamp('2026-08-31'))]
    support=pd.Timestamp('2026-09-01')
    support_ok=bool(support in all_dates and all_dates.get_loc(support)==all_dates.get_loc(eval_dates[-1])+1)

    fail_checks=sorted(k for k,v in validation.get('checks',{}).items() if v is not True)
    sample_evidence_ok=(
        validation.get('status')=='CHECK_REQUIRED'
        and fail_checks==['control_nav_coverage_at_least_90_percent']
        and benchmark.get('status')=='SAMPLE_COMPLETED'
        and benchmark.get('mode')=='SAMPLE'
        and int(benchmark.get('sample_ticker_count',-1))==32
        and int(benchmark.get('evaluated_ticker_count',-1))==32
        and int(benchmark.get('eligible_universe_ticker_count',-1))==2573
        and int(benchmark.get('available_price_ticker_count',-1))==32
        and int(benchmark.get('worker_error_count',-1))==0
        and int(benchmark.get('workers',-1))==10
        and float(benchmark.get('estimated_full_wall_seconds',1e20))<7200
        and benchmark.get('full_run_authorized_by_sample_contract') is True
    )
    source_preflight_hash=sha(V01/'preflight.json')
    old_preflight_record=v01_manifest.get('p2_2_execution',{}).get('preflight_sha256')
    authority_paths=[
        'data/market/rolling_authority/manifest.json',
        'data/market/rolling_authority/merged_pit_intervals.json',
        'data/market/rolling_authority/merged_trading_calendar.json',
    ]
    authority_hashes={p:sha(ROOT/p) for p in authority_paths}
    internal_rolling_hash=json.loads((ROOT/'data/market/rolling_authority/manifest.json').read_text()).get('manifest_sha256')
    p3_hashes={
        'p3_1_execution_contract':sha(P31/'execution_contract.json'),
        'p3_1_replay':sha(P31/'run_official_realistic_replay.py'),
        'p3_1_117_portfolio_replay':sha(ROOT/'artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_117_price_nav_closure_v01/run_portfolio_replay.py'),
        'p3_1_117_targeted_evaluation':sha(ROOT/'artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_117_price_nav_closure_v01/run_targeted_evaluation.py'),
        'p3_2_replay':sha(P32/'run_official_realistic_replay.py'),
        'p3_2_gate_readjudication':sha(ROOT/'artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_official_gate_readjudication_v01/gate_results.json'),
        'p3_2_data_nav_replay_decision':sha(ROOT/'artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_2_data_nav_closure_v01/replay_decision.json'),
    }
    preflight_universe=preflight.get('universe',{})
    input_summary=preflight.get('repository_v2_input_preflight',{})
    raw_summary=preflight.get('krx_raw_signal_partition_preflight',{})
    checks={
        'baseline_main_head_origin_equal':branch=='main' and head==origin,
        'tracked_tree_clean':tracked_clean,
        'v01_source_manifest_internal_hashes_match':len(final_match)==len(v01_manifest['files'])-1 and len(final_bad)==0 and len(stale_directive)==1,
        'v01_pre_sample_manifest_known_post_sample_edits_only':set(old_diff)=={
            '/Users/june/Documents/projects/w.md',
            'artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p2_2_official_realistic_portfolio_v01/run_p2_2_replay.py',
            'artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p2_2_official_realistic_portfolio_v01/validate_sample_p2_2.py',
            'artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p2_2_official_realistic_portfolio_v01/finalize_p2_2.py',
            'artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p2_2_official_realistic_portfolio_v01/seal_source_manifest.py',
        },
        'v01_artifact_hashes_match':len(artifact_match)==len(artifact_hashes['files']) and not artifact_bad,
        'v01_preflight_sha_matches_manifest':source_preflight_hash==old_preflight_record,
        'adjusted_price_files_all_match':len(prices)==2573 and not adjusted_bad and input_summary.get('adjusted_file_hash_inventory_count')==2573,
        'raw_partitions_all_match':len(raw_rows)==2776 and not raw_bad and not raw_missing and sum(1 for x in raw_rows if x['status']=='COMPLETE')==2776,
        'raw_manifest_database_hash_matches_v01_source':db_hash=='ee0c5beac81f8cdfbe0751803ed2f171607e0c24da59660e3d9137104229a103',
        'rolling_authority_hashes_match_v01_source':authority_hashes=={
            'data/market/rolling_authority/manifest.json':'5c4a9e346d7460c4a28b30a3cd9ab19c9c17527f1c4409282206e8ec2a731570',
            'data/market/rolling_authority/merged_pit_intervals.json':'d93a958d7bbae9142ef1fa5aded36080d1d107739e777eb4ec3b6566fea90654',
            'data/market/rolling_authority/merged_trading_calendar.json':'ab7635de160e06d538d9d0dc7225c8e1b307f191f54f2584d4c79e47a94a7480',
        },
        'rolling_authority_internal_hash_matches_preflight':internal_rolling_hash==preflight.get('date_authorities',{}).get('calendar_manifest_sha256'),
        'permanent_exclusions_exactly_182_and_hash_match':len(pairs)==182 and canonical=='9091a40d5dfc3dc115e00166ea3ef806ef5a4ca3b595d76864598ec050904b12' and registry_sha==preflight_universe.get('permanent_exclusion_file_sha256'),
        'required_380440_pair_excluded':('380440','KR7380440008') in pairs and preflight_universe.get('380440_in_eligible_universe') is False,
        'current_p2_authority_1387_sessions_and_2573_tickers':len(eval_dates)==1387 and eval_dates[0]==pd.Timestamp('2021-01-04') and eval_dates[-1]==pd.Timestamp('2026-08-31') and len(segments)==2573,
        'support_date_is_next_exact_krx_session':support_ok,
        'v01_preflight_unclassified_source_rows_zero':input_summary.get('raw_only_unclassified_sessions_total')==0 and input_summary.get('adjusted_only_unexplained_sessions_total')==0,
        'current_code_hashes_match_v01_final_manifest':all(required_code_match.values()),
        'representative_sample_all_checks_except_control_nav_coverage_pass':sample_evidence_ok,
        'worker_count_stays_10_and_external_api_calls_zero':benchmark.get('workers')==10 and preflight.get('external_api_requests')==0,
    }
    ok=all(checks.values())
    result={
        'schema':'fast_core_v2_alignment_500b_p2_2_preflight_reuse_audit_v02',
        'task_id':'FAST_CORE_V2_ALIGNMENT_500B_P2_2_OFFICIAL_FULL_RUN_V02',
        'status':'PASS' if ok else 'FAIL',
        'generated_utc':pd.Timestamp.utcnow().isoformat(),
        'baseline':{'branch':branch,'head':head,'origin_main':origin,'tracked_tree_clean':tracked_clean,'preexisting_untracked_preserved':True},
        'v01_evidence':{
            'preflight_path':str((V01/'preflight.json').relative_to(ROOT)),
            'preflight_sha256':source_preflight_hash,
            'preflight_status':preflight.get('preflight_status'),
            'sample_validation_sha256':sha(V01/'sample_validation.json'),
            'sample_benchmark_sha256':sha(V01/'sample_benchmark.json'),
            'sample_validation_status':validation.get('status'),
            'sample_failed_checks':fail_checks,
            'sample_coverage_pct_control':validation.get('checks',{}).get('control_nav_coverage_at_least_90_percent'),
            'sample_benchmark':{k:benchmark.get(k) for k in ['sample_ticker_count','evaluated_ticker_count','eligible_universe_ticker_count','available_price_ticker_count','worker_error_count','workers','wall_seconds_including_portfolio_replays','estimated_full_wall_seconds','estimated_full_wall_hours','full_run_authorized_by_sample_contract','control_signal_trade_count','candidate_signal_trade_count','candidate_filter_status_counts']},
            'sample_execution_repeated':False,
            'sample_trade_outputs_used_as_full_run':False,
        },
        'manifest_audit':{
            'v01_final_source_manifest_files':len(v01_manifest['files']),
            'v01_final_source_manifest_internal_matches':len(final_match),
            'v01_final_source_manifest_internal_mismatches':final_bad,
            'stale_previous_w_directive_record':stale_directive,
            'current_w_sha256':sha(W),
            'v01_pre_sample_historical_manifest_files':len(old_manifest['files']),
            'v01_pre_sample_historical_matches':len(old_match),
            'expected_after_sample_patch_differences':sorted(old_diff),
            'v01_artifact_hash_files':len(artifact_hashes['files']),
            'v01_artifact_hash_matches':len(artifact_match),
            'v01_artifact_hash_mismatches':artifact_bad,
            'v01_adjusted_price_hash_rows':len(prices),
            'v01_adjusted_price_hash_matches':len(prices)-len(adjusted_bad),
            'adjusted_price_hash_mismatches':adjusted_bad[:20],
            'v01_raw_partition_rows':len(raw_rows),
            'current_raw_manifest_rows':len(current_manifest),
            'raw_partition_matches':len(raw_rows)-len(raw_bad)-len(raw_missing),
            'raw_partition_mismatches':raw_bad[:20],
            'raw_partition_missing_manifest_keys':raw_missing[:20],
            'raw_manifest_database_sha256':db_hash,
            'rolling_authority_file_sha256':authority_hashes,
            'rolling_authority_internal_manifest_sha256':internal_rolling_hash,
            'permanent_exclusion_count':len(pairs),
            'permanent_exclusion_source_sha256':registry_sha,
            'permanent_exclusion_canonical_sha256':canonical,
            'p3_source_hashes':p3_hashes,
            'current_w_sha256':sha(W),
        },
        'calendar_and_universe':{
            'exact_evaluation_sessions':len(eval_dates),
            'evaluation_start':eval_dates[0].strftime('%Y-%m-%d'),
            'evaluation_end':eval_dates[-1].strftime('%Y-%m-%d'),
            'support_session':'2026-09-01',
            'support_is_next_exact_session':support_ok,
            'calendar_frontier':all_dates[-1].strftime('%Y-%m-%d'),
            'eligible_tickers_after_exclusions':len(segments),
            'completed_ma60_warmup_months':preflight.get('date_authorities',{}).get('completed_ma60_month_count'),
            'warmup_first_month':preflight.get('date_authorities',{}).get('completed_ma60_first_month'),
            'warmup_last_month':preflight.get('date_authorities',{}).get('completed_ma60_last_month'),
            'unclassified_raw_only_sessions':input_summary.get('raw_only_unclassified_sessions_total'),
            'unexplained_adjusted_only_sessions':input_summary.get('adjusted_only_unexplained_sessions_total'),
        },
        'checks':checks,
        'sample_gate_policy':{
            'failed_sample_check_allowed_for_full_run_authorization':['control_nav_coverage_at_least_90_percent'],
            'all_other_sample_checks_required':True,
            'official_full_run_E_threshold_unchanged':True,
            'full_run_E_below_90_percent':'CHECK_REQUIRED',
        },
        'external_api_requests':0,
        'elapsed_seconds':round(time.perf_counter()-started,3),
        'runtime':{'python':sys.version.split()[0],'numpy':np.__version__,'pandas':pd.__version__},
        'full_run_started':False,
    }
    (OUT/'preflight_reuse_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':result['status'],'checks':checks,'elapsed_seconds':result['elapsed_seconds'],'path':str(OUT/'preflight_reuse_audit.json')},ensure_ascii=False,indent=2))
    if not ok: raise SystemExit(2)

if __name__=='__main__':
    run()
