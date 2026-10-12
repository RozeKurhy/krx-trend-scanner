import ast, csv, hashlib, json, subprocess
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
BASE = "29ac6c85af0524c279a41cb0d820b9b646671a91"
REG = "src/trend_scanner/universe/permanent_identity_exclusions.py"
TARGET = {("138580", "KR7138580006"), ("003410", "KR7003410008")}
R = ROOT / "artifacts/strategies/a_fast_core_v2/research"
P2 = R / "fast_core_v2_alignment_500b_p2_2_official_full_run_v02"
P31 = R / "fast_core_v2_alignment_500b_p3_1_117_price_nav_closure_v01"
P32 = R / "fast_core_v2_alignment_500b_p3_2_official_realistic_v01"
P32C = R / "fast_core_v2_alignment_500b_p3_2_data_nav_closure_v01"
P32R = R / "fast_core_v2_alignment_500b_p3_2_official_gate_readjudication_v01"

def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()

def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()

def write_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

def registry(text):
    tree = ast.parse(text)
    node = next(n for n in tree.body if isinstance(n, ast.AnnAssign) and getattr(n.target, "id", "") == "PERMANENT_IDENTITY_EXCLUSIONS")
    return ast.literal_eval(node.value)

def canonical(d):
    pairs = sorted((str(t).zfill(6), str(i).upper()) for t, i in d)
    body = json.dumps({"schema":"sorted_exact_pair_json_v01","pairs":[list(x) for x in pairs]}, ensure_ascii=False, sort_keys=True, separators=(",",":"))
    return sha_bytes(body.encode())

def readcsv(path):
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), list(reader)

def writecsv(path, fields, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

def pair(row):
    return (str(row.get("ticker","")).zfill(6), str(row.get("isu_cd",row.get("standard_isu_cd",""))).strip().upper())

def check_artifacts(directory):
    manifest = json.loads((directory/"artifact_hashes.json").read_text())
    good, bad = [], []
    for item in manifest.get("files", []):
        f = directory/item["path"]
        if not f.is_file() or f.stat().st_size != int(item["bytes"]) or sha(f) != item["sha256"]:
            bad.append({"bundle":directory.name,"path":item["path"]})
        else:
            good.append({"bundle":directory.name,"path":item["path"],"sha256":item["sha256"],"bytes":item["bytes"],"status":"MATCH"})
    return good,bad

def gates_p31(d):
    out={}
    for group, metrics in d["P3-1"].items():
        out[group]={k:v.get("status") for k,v in metrics.items() if k in {"A_integrity","B_costs","C_profitability","D_mdd","E_validity"}}
    return out

def audit_period(period, event_dir, signal_dir, audit_dir, gate_path, integrity_path):
    gates=json.loads(gate_path.read_text())
    if period=="P3-1":
        gate_status=gates_p31(gates)
        overall="PASS_WITH_OBSERVED_NAV" if all(
            gate_status[g].get(k)=="PASS" for g in gate_status for k in ("A_integrity","B_costs","C_profitability","D_mdd")
        ) and all(gate_status[g].get("E_validity")=="OBSERVED" for g in gate_status) else "CHECK_REQUIRED"
    else:
        gate_status=gates["groups"]
        overall=gates.get("overall_status","CHECK_REQUIRED")
    specs=[
        (signal_dir,"control_signal_trade_inputs.csv"),
        (signal_dir,"control_trades.csv"),
        (signal_dir,"candidate_signal_trade_inputs.csv"),
        (signal_dir,"candidate_trades.csv"),
        (audit_dir,"candidate_signal_filter_audit.csv"),
        (event_dir,"control_portfolio_events.csv"),
        (event_dir,"candidate_portfolio_events.csv"),
        (event_dir,"control_cash_events.csv"),
        (event_dir,"candidate_cash_events.csv"),
    ]
    effects=[]; evidence=[]; target_events=[]; cand_status={}
    n_control=n_candidate=0
    for directory,name in specs:
        f=directory/name
        if not f.is_file(): continue
        fields,rows=readcsv(f)
        removed=[r for r in rows if pair(r) in TARGET]
        effects.append({"path":str(f.relative_to(ROOT)),"sha256":sha(f),"before":len(rows),"removed":len(removed),"after":len(rows)-len(removed)})
        if name in {"control_signal_trade_inputs.csv","control_trades.csv"}: n_control=max(n_control,len(removed))
        if name in {"candidate_signal_trade_inputs.csv","candidate_trades.csv"}: n_candidate=max(n_candidate,len(removed))
        if name=="candidate_signal_filter_audit.csv":
            for r in removed:
                s=r.get("candidate_status","")
                cand_status[s]=cand_status.get(s,0)+1
                evidence.append({"period":period,"source_file":name,"ticker":pair(r)[0],"isu_cd":pair(r)[1],"signal_date":r.get("signal_date",""),"trade_id":r.get("trade_id",""),"event_type":"","event_status":s,"cash_before_krw":"","cash_after_krw":"","source_sha256":sha(f)})
        if name.endswith("_portfolio_events.csv") or name.endswith("_cash_events.csv"):
            for r in removed:
                before=r.get("cash_before_krw",""); after=r.get("cash_after_krw","")
                evidence.append({"period":period,"source_file":name,"ticker":pair(r)[0],"isu_cd":pair(r)[1],"signal_date":r.get("signal_date",""),"trade_id":r.get("trade_id",""),"event_type":r.get("event_type",""),"event_status":r.get("event_status",""),"cash_before_krw":before,"cash_after_krw":after,"source_sha256":sha(f)})
                target_events.append((name,r))
    cash_skip=bool(target_events) and all(
        r.get("event_type")=="ENTRY" and r.get("event_status")=="SKIPPED_CASH_UNAVAILABLE"
        and r.get("cash_before_krw","")!="" and r.get("cash_after_krw","")
        and abs(float(r["cash_before_krw"])-float(r["cash_after_krw"]))<=1e-8
        for _,r in target_events
    )
    status_ok=(overall=="PASS_WITH_OBSERVED_NAV")
    pre= n_control==3 and n_candidate==0 and cash_skip and status_ok
    return {
        "schema":period.lower()+"_exclusion184_rejudgment_v01",
        "source_directories":{"event_ledgers":str(event_dir.relative_to(ROOT)),"signal_ledgers":str(signal_dir.relative_to(ROOT)),"candidate_filter_audit":str(audit_dir.relative_to(ROOT))},
        "official_gate_file":str(gate_path.relative_to(ROOT)),
        "integrity_file":str(integrity_path.relative_to(ROOT)),
        "pair_row_effects":effects,
        "removed_candidate_filter_status_counts":cand_status,
        "removed_control_signal_trade_rows":n_control,
        "removed_candidate_signal_trade_rows":n_candidate,
        "removed_target_portfolio_or_cash_event_rows":len(target_events),
        "all_target_events_are_cash_skips_with_zero_cash_delta":cash_skip,
        "excluded_pair_execution_or_position_count":0 if cash_skip and n_candidate==0 and n_control==3 else None,
        "nonexcluded_event_cash_rows_preserved_exactly":True,
        "daily_nav_and_metrics_replay_required":False,
        "daily_nav_and_metrics_unchanged_reason":"Removed events are SKIPPED_CASH_UNAVAILABLE entries and cash_before_krw equals cash_after_krw; no target position, proceeds, fees or mark was present.",
        "official_gate_status_before_and_after":{"before":gate_status,"after":gate_status},
        "single_period_status_before_and_after":{"before":overall,"after":overall},
        "five_window_adoption":"NOT_FINAL_5WINDOW",
        "candidate_promotion":"NOT_EVALUATED",
        "official_default_remains":"PATTERN_A_FAST_FINAL_STRATEGY_V02",
        "requires_full_signal_rerun":False,
        "preconditions_pass":pre,
        "removed_row_evidence":evidence,
    }

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    head=subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()
    origin=subprocess.check_output(["git","rev-parse","origin/main"],cwd=ROOT,text=True).strip()
    if head!=BASE or origin!=BASE: raise RuntimeError(f"BASELINE_MISMATCH:{head}:{origin}")
    base_bytes=subprocess.check_output(["git","show",f"{BASE}:{REG}"],cwd=ROOT)
    old=registry(base_bytes.decode()); new=registry((ROOT/REG).read_text())
    additions=sorted(set(new)-set(old)); removals=sorted(set(old)-set(new))
    if len(old)!=182 or len(new)!=184 or set(additions)!=TARGET or removals or not all(new[k]==v for k,v in old.items()):
        raise RuntimeError(f"POLICY_DELTA_INVALID:{len(old)}:{len(new)}:{additions}:{removals}")
    old_hash=canonical(old); new_hash=canonical(new)
    if old_hash!="9091a40d5dfc3dc115e00166ea3ef806ef5a4ca3b595d76864598ec050904b12": raise RuntimeError("OLD_CANONICAL_HASH_MISMATCH")
    bundle_dirs=[P31,P32,P32C,P32R,P2]
    evidence=[]; failures=[]
    for directory in bundle_dirs:
        good,bad=check_artifacts(directory); evidence.extend(good); failures.extend(bad)
    if failures: raise RuntimeError(f"REFERENCE_ARTIFACT_HASH_FAILURE:{failures[:5]}")
    old_manifest=json.loads((P2/"source_manifest.json").read_text())
    source_matches=[]; source_bad=[]
    for item in old_manifest.get("files",[]):
        f=Path(item.get("absolute_path") or item["path"])
        content=base_bytes if item["path"]==REG else (f.read_bytes() if f.is_file() else None)
        if content is None or sha_bytes(content)!=item["sha256"] or len(content)!=int(item["bytes"]):
            source_bad.append(item["path"])
        else: source_matches.append(item["path"])
    if source_bad: raise RuntimeError(f"FROZEN_SOURCE_MANIFEST_BAD:{source_bad[:5]}")

    policy={
        "schema":"fast_core_v2_alignment_500b_permanent_exclusion_policy_transition_v01",
        "baseline_commit":BASE,"baseline_pair_count":len(old),"current_pair_count":len(new),
        "added_exact_pairs":[{"ticker":t,"standard_isu_cd":i,**new[(t,i)]} for t,i in additions],
        "removed_exact_pairs":[],"preexisting_182_entries_unchanged":True,
        "baseline_source_sha256":sha_bytes(base_bytes),"current_source_sha256":sha(ROOT/REG),
        "canonical_hash_scheme":"sorted_exact_pair_json_v01","baseline_canonical_sha256":old_hash,"current_canonical_sha256":new_hash,
        "previous_p2_source_manifest_files":len(old_manifest["files"]),
        "previous_p2_source_manifest_matches_using_baseline_registry":len(source_matches),
        "previous_p2_source_manifest_mismatches":source_bad,
        "verified_reference_artifact_files":len(evidence),"reference_artifact_failures":failures,
        "approval_scope":"GLOBAL; all strategies and five validation windows",
        "approval_date":"2026-10-12",
        "reason_basis":"unresolved special corporate-action settlement/lifecycle accounting and valuation; generic implementation is not economically justified; not performance-based",
    }
    write_json(OUT/"exclusion_policy_audit.json",policy)
    with (OUT/"identity_policy_transition.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=["baseline_pair_count","current_pair_count","ticker","standard_isu_cd","transition","current_canonical_sha256","baseline_source_sha256","current_source_sha256"])
        w.writeheader()
        for t,i in additions: w.writerow({"baseline_pair_count":len(old),"current_pair_count":len(new),"ticker":t,"standard_isu_cd":i,"transition":"ADDED_GLOBAL_PERMANENT_EXCLUSION","current_canonical_sha256":new_hash,"baseline_source_sha256":sha_bytes(base_bytes),"current_source_sha256":sha(ROOT/REG)})

    p31=audit_period("P3-1",P31,P31,P31,P31/"gate_results.json",P31/"integrity_validation.json")
    p32=audit_period("P3-2",P32C,P32,P32,P32R/"gate_results.json",P32R/"integrity_audit.json")
    write_json(OUT/"p3_1_rejudgment.json",p31); write_json(OUT/"p3_2_rejudgment.json",p32)
    if not p31["preconditions_pass"] or not p32["preconditions_pass"]:
        raise RuntimeError("P3_POLICY_IMPACT_NOT_PROVEN; P2_REPLAY_NOT_STARTED")

    p2_rows={}; removed=[]
    for name in ["control_trades.csv","candidate_trades.csv","candidate_signal_filter_audit.csv"]:
        f=P2/name; fields,rows=readcsv(f)
        excluded=[r for r in rows if pair(r) in TARGET]
        kept=[r for r in rows if pair(r) not in TARGET]
        writecsv(OUT/name,fields,kept)
        p2_rows[name]={"source_sha256":sha(f),"rows_before":len(rows),"removed_exact_pair_rows":len(excluded),"rows_after":len(kept)}
        for r in excluded:
            removed.append({"source_file":name,"ticker":pair(r)[0],"isu_cd":pair(r)[1],"signal_date":r.get("entry_signal_date",r.get("signal_date","")),"trade_id":r.get("trade_id",""),"candidate_status":r.get("candidate_status",""),"event_type":"","event_status":""})
    control=readcsv(OUT/"control_trades.csv")[1]; candidate=readcsv(OUT/"candidate_trades.csv")[1]; audit=readcsv(OUT/"candidate_signal_filter_audit.csv")[1]
    if any(pair(r) in TARGET for r in control+candidate+audit): raise RuntimeError("P2_EXCLUDED_PAIR_LEAKAGE")
    if not control or not candidate or not audit: raise RuntimeError("P2_FILTERED_INPUT_EMPTY")
    writecsv(OUT/"control_signal_trade_inputs.csv",list(control[0]),control)
    writecsv(OUT/"candidate_signal_trade_inputs.csv",list(candidate[0]),candidate)
    writecsv(OUT/"p2_2_removed_signal_row_evidence.csv",["source_file","ticker","isu_cd","signal_date","trade_id","candidate_status","event_type","event_status"],removed)
    for name in ["raw_partition_preflight.csv","signal_date_krx_partition_hashes.csv"]:
        src=P2/name
        if src.is_file(): (OUT/name).write_bytes(src.read_bytes())
    for srcname,outname in [("preflight.json","p2_v02_preflight_182.json"),("execution_contract.json","p2_v02_execution_contract_182.json"),("source_manifest.json","p2_v02_source_manifest_182.json")]:
        (OUT/outname).write_bytes((P2/srcname).read_bytes())
    good,bad=[],[]
    for label,directory in [("P3_1",P31),("P3_2",P32),("P3_2_CLOSURE",P32C),("P3_2_READJ",P32R),("P2_2_V02",P2)]:
        x,y=check_artifacts(directory); good.extend([{**a,"bundle":label} for a in x]); bad.extend(y)
    with (OUT/"source_artifact_hash_evidence.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=["bundle","path","sha256","bytes","status"]); w.writeheader(); w.writerows(good)
    p2audit={
        "schema":"fast_core_v2_alignment_500b_p2_2_exclusion_184_saved_signal_input_audit_v01",
        "source_directory":str(P2.relative_to(ROOT)),"source_artifact_hashes_verified":True,
        "signal_generation_reused":True,"signal_evaluation_run_count":0,"portfolio_replay_started":False,
        "removed_rows_by_file":p2_rows,"removed_rows_by_identity":removed,
        "remaining_control_signal_rows":len(control),"remaining_candidate_signal_rows":len(candidate),"remaining_candidate_filter_audit_rows":len(audit),
        "exact_target_leakage_after_filter":0,"expected_current_ticker_count":2571,
        "count_provisional_until_current_authority_check":True,
        "five_window_adoption":"NOT_FINAL_5WINDOW","candidate_promotion":"NOT_EVALUATED",
    }
    write_json(OUT/"p2_2_input_exclusion_audit.json",p2audit)
    policy.update({"reference_artifact_file_count":len(good),"reference_artifact_hash_failures":bad})
    write_json(OUT/"exclusion_policy_audit.json",policy)
    plan=f"""# FAST Core V2 exclusion-184 policy transition and P2-2 replay V01

- Work ID: FAST_CORE_V2_ALIGNMENT_500B_EXCLUDE_2_P3_READJUDGE_P2_2_REPLAY_V01
- Baseline: main {BASE}; origin/main matched before the policy edit and replay.
- Add only exact pairs 138580/KR7138580006 and 003410/KR7003410008 to the global permanent-identity registry.
- Sequence: registry transition; read-only P3-1 and P3-2 impact audit and A-E re-judgment; then one P2-2 CONTROL and one ALIGNMENT + 500B portfolio replay from the verified frozen signal ledgers after deleting these exact identities.
- P1 and P2-1 are not run. No other identity is excluded; no strategy, filter, fill, cost, settlement, evaluator, web or operating code is changed; no automatic promotion.
- Period: 2021-01-04 through 2026-08-31, 1,387 exact KRX sessions. 2026-09-01 supports exits only. Completed monthly MA60/MA20 warmup remains 2016-01 through 2020-12.
- Contract: KRW 200,000,000 initial cash; KRW 5,000,000 inclusive buy budget; integer shares; no partial fills or artificial position cap; 0.1% adverse slippage and 0.015% commission each side; 0% tax; T+1 sale proceeds; no same-open reuse; deterministic entry order.
- No carry, interpolation, zero mark or invented corporate-action settlement. Coverage under 90% remains CHECK_REQUIRED.
- Saved V02 signal/filter ledgers are reused; no signal evaluator rerun. Full CONTROL and candidate portfolio replay runs once per group.
- Output: {OUT.relative_to(ROOT).as_posix()}
"""
    (OUT/"plan.md").write_text(plan,encoding="utf-8")
    contract={
        "schema":"fast_core_v2_alignment_500b_p2_2_execution_contract_exclusion_184_v01",
        "baseline_head":BASE,"baseline_origin_main":BASE,"window":"P2-2","start":"2021-01-04","cutoff":"2026-08-31","sessions":1387,"support_date":"2026-09-01","support_date_in_nav":False,
        "initial_capital_krw":200000000,"per_position_inclusive_buy_budget_krw":5000000,"integer_shares":True,"partial_fills":False,"artificial_position_cap":None,
        "slippage_each_side":0.001,"commission_each_side":0.00015,"sell_tax":0,"sale_proceeds_settlement":"T+1","same_open_sale_proceeds_reuse":False,"cutoff_open_hypothetical_liquidation":False,
        "signal_reuse":{"source":str(P2.relative_to(ROOT)),"signal_evaluation_run_count":0,"removed_exact_pairs":[list(x) for x in sorted(TARGET)]},
        "permanent_exclusion_policy":{"pair_count":184,"canonical_hash_scheme":"sorted_exact_pair_json_v01","canonical_sha256":new_hash,"additions_only":[list(x) for x in sorted(TARGET)]},
        "official_gates":{"A":"PIT, identity, lifecycle, cash and event integrity","B":"filled-side costs and cash conservation","C":"positive total return and CAGR","D":"MDD >= -40%; candidate relative degradation < +5 percentage points","E":"valid full-portfolio NAV coverage >= 90%; below 90% is CHECK_REQUIRED","cash shortage rate":"diagnostic only"},
        "not_run":["P1","P2-1","P3 replay/signal evaluation","web or production changes"],
        "five_window_adoption":"NOT_FINAL_5WINDOW","candidate_promotion":"NOT_EVALUATED","official_default":"PATTERN_A_FAST_FINAL_STRATEGY_V02"
    }
    write_json(OUT/"execution_contract.json",contract)
    print(json.dumps({"status":"PREFLIGHT_INPUTS_READY","pairs_before":len(old),"pairs_after":len(new),"added":additions,"canonical_sha256":new_hash,"reference_artifact_files":len(good),"p3_1_ready":p31["preconditions_pass"],"p3_2_ready":p32["preconditions_pass"],"p2_signal_rows":{"CONTROL":len(control),"candidate":len(candidate),"audit":len(audit)},"p2_removed_rows":p2_rows,"path":str(OUT),"timestamp_kst":datetime.now(ZoneInfo("Asia/Seoul")).isoformat()},ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()

