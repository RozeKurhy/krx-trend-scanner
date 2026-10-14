# A FAST Core V2 Alignment 500B V08 Reference Baseline Approval

**승인 상태:** `V08_REFERENCE_BASELINE_APPROVED`

**기존 V02 차이 상태:** `G6_V02_DIFFERENCE_PRESERVED`

**승인일:** 2026-10-14 (KST)

**작업 ID:** `A_FAST_ALIGNMENT_500B_V08_BASELINE_APPROVAL_COMMIT_PUSH_V01`

## 승인 범위

V08에서 독립적으로 재현된 digest를 향후 **웹 전 기간 재생의 staging 비교 기준**으로 승인한다. 이는 비교 기준만 지정하며 운영 canonical 교체, `web/data` 게시, Phase4E 전파, 기본 전략 활성화, 실제 신호일 지정 또는 실거래를 승인하지 않는다. 기본 V2의 운영 활성 상태는 유지한다.

| 항목 | 승인 기준 |
|---|---|
| 요청 기준일 / 시장 기준일 | `2026-10-11` / `2026-10-08` |
| COMMON 종목 수 | 1,459 |
| V08 reference digest | `e3c6ecc19187eb8951c1c9ef1626a2b54a9cffe1f6d415721b75a0cca8e89b61` |
| sealed V02 digest | `b81d708f8794381e6e9a37c0dad8c9811163f199401af87a057f6bcfb271cbb1` |
| V08 reproduction | PASS; worker 5/5, 오류 0; JSON/Markdown 각 1,459 |
| 거래 및 Gate | 거래 423 (실현 398, cutoff 미종료 25); gate audit 20,012 |
| 정확 비교 | 정규화 core 1,459/1,459; 상태·포지션·액션 1,459/1,459; 거래 423/423; gate 20,012/20,012 |
| sealed V02 G6 digest parity | **FAIL 유지**. V08 digest 재현 PASS와 별도 판정 |

## 재현 및 소스 근거

V08 final audit는 R1–R7 및 V08 후보 재현 검증을 PASS로 판정했다. 200개 프로젝트 source hash와 9,822개 입력 hash의 재검증 오류는 각각 0건이다. 보호 hash 4,461개는 변경되지 않았고, worker alias 40개는 모두 검증됐다. PIT 재검사는 41/41 종목 통과했으며 KRX 시가총액 partition 968개를 확인했다.

반영하는 source 수정은 `src/trend_scanner/reporting/stock_report.py`의 FAST full-history replay 입력 조회에 한정된다. `HISTORICAL_ALIGNMENT_REPLAY_MODE`, `repository is not None`, `daily_override is None` 조건에서만 `RepositoryV2DailyLoader(..., historical_identity=False)`를 호출한다. 기존 일반 일봉 조회와 다른 replay mode의 경로는 유지한다. 수정 source SHA-256은 `49082389b8a4783e445605c12c0bd4f92e9046a21b121e321e070bdfc8600ddd`이며 V08 source manifest의 파일 hash와 일치한다.

### 77종목 V02 차이 보존

독립 FAST 주봉 계약 검증은 77개 차이 종목과 3개 대조군에서 통과했다. 새 core는 77/77에서 2026-10-02 완료 주봉 Stage와 일치했고, sealed V02 core의 Stage는 77/77에서 2026-09-30 월말 Stage와 일치했다. V02 대비 action 변경은 0건이다. 이 계산 기준 차이는 기존 V02 G6 FAIL의 설명 근거로 연결하되, sealed V02 digest를 변경하거나 PASS로 바꾸지 않는다. 당시 V02 미커밋 소스 및 일봉 row hash 계보는 확보되지 않았으므로 과거 입력값의 byte-level parity를 주장하지 않는다.

## 검증 기록

- V08 필수 회귀 묶음: 164 passed, 0 failed; 2,690 warnings.
- 코드 변경 검증: 245 passed, 0 failed; 6,667 warnings. FAST/Phase4B와 일반 stock report, Repository V2, B Select, Julia 경로 관련 테스트를 포함했다. warning은 억제하지 않았다.
- 기존 V02 canonical, web 데이터, source artifact, G6 상태는 수정하지 않았다.
- 새 reference는 향후 staging 결과와 비교할 때만 사용한다. staging 승격은 별도 승인 및 별도 심사를 거쳐야 한다.

## 증거 위치와 SHA-256

V08 증거 디렉터리: `artifacts/strategies/a_fast_core_v2/research/fast_core_v2_phase4b_source_bound_replay_v08/run_20261014/`

| 증거 | SHA-256 |
|---|---|
| `source_execution_manifest.json` | `4fa1b22f1c1a96aba7b6a40dd43b3c5fa3e00fdf234e18c4efa47592da62b0c8` |
| `input_authority_manifest.json` | `92dbfb569a31d1e04dfe9a433932ec5998f06271ef4cc2ca25db101945742040` |
| `final_audit.json` | `8df1bd26938b62db8e3842542b033d8948c895793887dfc5edd194c4ab59fd13` |
| `validation_summary.json` | `e46e2e202c835eae25ec2882513aa0074bad4c60571325789696ffb2404fff2c` |
| `phase4b_1459_execution.json` | `8e19735a82b6707f49a99d2de9ca57559442d57625c227e939ab1860be1118d1` |
| `phase4b_1459_candidate_core_parity.csv` | `80e6fb62bf4c09064e93724bb4a66b7a5436ef3e694a5c33cdafa8a1b4beaf09` |

77종목 원인 및 독립 계약 검증 자료는 다음 run에 있다.

- `artifacts/strategies/a_fast_core_v2/research/fast_core_v2_phase4b_g6_77_core_parity_rca_v01/run_20261014/report.md`
- `artifacts/strategies/a_fast_core_v2/research/fast_core_v2_phase4b_g6_77_independent_contract_validation_v01/run_20261014/validation_summary.json`
