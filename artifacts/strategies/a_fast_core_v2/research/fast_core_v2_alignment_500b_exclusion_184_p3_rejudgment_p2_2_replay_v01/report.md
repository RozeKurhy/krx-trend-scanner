# FAST Core V2 Alignment + 500B — 영구 제외 184쌍 반영, P3 재판정 및 P2-2 재생 V01

| 심각도 | 독립 원인 수 | 사유 |
|---|---:|---|
| CRITICAL | 0 | 없음 |
| MAJOR | 0 | 공식 게이트를 막는 별도 구조 오류 없음 |
| MINOR | 3 | 종목별 adjusted OHLC 행의 `HIGH_LT_CLOSE`; 미해결 mark는 UNRESOLVED로 유지하고 carry/보간하지 않음 |

**P2-2 단일 기간 공식 판정: PASS_WITH_OBSERVED_NAV.** A~D는 양 그룹 PASS, E는 관측 NAV로 OBSERVED야. 이 결과는 5기간 종합 채택이나 후보 승격을 뜻하지 않아.

## 정책 변경과 출처

- 실행 기준 Git: `29ac6c85af0524c279a41cb0d820b9b646671a91`; 실행 직전 HEAD와 origin/main이 일치했어. 기존 registry 182 exact pairs는 유지했고 신규는 2쌍만 추가했어 (`+2 / -0`, 다른 pair 변경 0).
- 신규 exact pair canonical hash (`sorted_exact_pair_json_v01`): `5d3bd9a1e27e7e558235f0fba211263cdc90eb0b477978c8338eb019b1a6ec2e`. Registry source SHA-256: `0bb2e441cf428df56ad94ab33b08fd033737ee9216029016311b5cb3524d8d3a`. 기준선 182-pair hash: `9091a40d5dfc3dc115e00166ea3ef806ef5a4ca3b595d76864598ec050904b12`.
- 승인 사유는 두 exact identity의 미해결 주식교환·현금대가 정산/가치평가와 범용 처리 구현의 비경제성이야. 과거 손익·승률을 이유로 삼지 않았고, 다른 ticker/ISU는 추가 제외하지 않았어.
- `source_manifest.json`은 입력·코드·계약 300/300개 hash 일치. 과거 P2 source 106/106 및 P3 sealed artifacts 194/194 검증 결과도 `exclusion_policy_audit.json`과 `source_artifact_hash_evidence.csv`에 보존했어.
- authority 문서와 수정된 registry의 SHA-256은 `authority_hashes.json`에 있어. 전략 evaluator/체결/비용/웹/운영 코드는 수정하지 않았어.

## P3-1 / P3-2 영향 감사와 A~E 재판정

두 기간은 저장된 공식 거래·현금·NAV 원장만 읽었고 전수 신호 재계산이나 portfolio replay는 하지 않았어. 제거된 target 거래행은 CONTROL 3건씩이고 모두 `SKIPPED_CASH_UNAVAILABLE`; cash_before와 cash_after가 같아. 후보 target trade/fill은 0건이고 관련 후보 filter audit 행은 각 20건이 거절 상태였어. 비제외 event/cash rows, NAV 및 성과는 exact 동일해.

| 기간 | 그룹 | 거래일 | 총수익률 | CAGR | Observed MDD | NAV coverage | NAV 누락 | 공식 A~E |
|---|---|---:|---:|---:|---:|---:|---:|---|
| P3-1 | CONTROL | 834 | 14.61% | 4.09% | -38.70% | 99.88% | 1 | PASS/PASS/PASS/PASS/OBSERVED |
| P3-1 | ALIGNMENT_MCAP_500B | 834 | 30.70% | 8.19% | -13.64% | 99.52% | 4 | PASS/PASS/PASS/PASS/OBSERVED |
| P3-2 | CONTROL | 1139 | 31.78% | 6.11% | -38.70% | 99.91% | 1 | PASS/PASS/PASS/PASS/OBSERVED |
| P3-2 | ALIGNMENT_MCAP_500B | 1139 | 108.23% | 17.06% | -13.64% | 99.65% | 4 | PASS/PASS/PASS/PASS/OBSERVED |

- P3-1/P3-2 양쪽 모두 `PASS_WITH_OBSERVED_NAV` 유지. 기존 A~E 수치와 비제외 cash/event/NAV 흐름이 그대로인 근거는 `p3_1_rejudgment.json`, `p3_2_rejudgment.json`, `p3_1_gate_results.json`, `p3_2_gate_results.json`이야.

## P2-2 동결 신호 재사용과 전체 포트폴리오 재생

- P2 V02의 동결 signal/filter ledger를 hash·PIT·identity·전략 버전 기준으로 확인하고 정확한 신규 pair 행만 제거했어. CONTROL trade 4행, 후보 trade 1행, 후보 filter audit 21행을 제외한 뒤 재생했어. 잔여 ledger는 CONTROL 2,283행, 후보 282행, 후보 filter audit 9,062행이야.
- 평가 구간 2021-01-04~2026-08-31의 정확한 KRX 1,387 sessions를 새 cash path로 chronological replay했어. 2026-09-01은 exit 지원만 했고 NAV/성과에 포함하지 않았어. 신호 평가 0회; CONTROL/후보 portfolio replay 각각 1회; worker 오류 0; retry 0; replay journal 완료.

| A~E | CONTROL | ALIGNMENT_MCAP_500B |
|---|---|---|
| A 무결성 | PASS | PASS |
| B 비용 | PASS | PASS |
| C 수익성 | PASS | PASS |
| D MDD | PASS | PASS |
| E NAV 유효성 | OBSERVED | OBSERVED |

| 지표 | CONTROL | 후보 | 후보−CONTROL |
|---|---:|---:|---:|
| 종료 자산(원) | 365,230,670.59 | 407,509,388.00 | 42,278,717.42 |
| 총수익률(%) | 82.62 | 103.75 | 21.14 |
| CAGR(%) | 11.24 | 13.42 | 2.18 |
| Observed MDD(%) | -36.87 | -18.75 | 18.11 |
| NAV coverage(%) | 99.86 | 99.28 | -0.58 |
| NAV 결측일 | 2.00 | 10.00 | 8.00 |
| 진입 시도 | 2,283.00 | 282.00 | -2,001.00 |
| 현금 부족 skip | 1,821.00 | 29.00 | -1,792.00 |
| 현금 부족률(%) | 79.76 | 10.28 | -69.48 |
| 실제 매수 | 462.00 | 253.00 | -209.00 |
| 실현 청산 | 414.00 | 233.00 | -181.00 |
| cutoff 미청산 | 48.00 | 20.00 | -28.00 |
| 실현 거래 | 414.00 | 233.00 | -181.00 |
| 승률(%) | 26.81 | 37.34 | 10.53 |
| 평균 순수익률(%) | 6.59 | 15.51 | 8.92 |
| 중앙 순수익률(%) | -15.63 | -14.97 | 0.66 |
| 평균 보유 거래일 | 99.96 | 127.93 | 27.97 |
| 중앙 보유 거래일 | 55.00 | 86.00 | 31.00 |
| 최대 수익률(%) | 434.05 | 249.20 | -184.85 |
| 최대 손실률(%) | -35.80 | -44.39 | -8.60 |
| +20% 이상 | 89.00 | 71.00 | -18.00 |
| +50% 이상 | 58.00 | 51.00 | -7.00 |
| +100% 이상 | 24.00 | 18.00 | -6.00 |
| -10% 이하 | 293.00 | 142.00 | -151.00 |
| -15% 이하 | 253.00 | 116.00 | -137.00 |
| -20% 이하 | 23.00 | 10.00 | -13.00 |
| -30% 이하 | 5.00 | 5.00 | 0.00 |
| Loss Guard 진입 | 284.00 | 136.00 | -148.00 |
| PROGRESSED 진입 | 149.00 | 109.00 | -40.00 |
| 평균 자본 활용률(%) | 91.20 | 59.54 | -31.66 |
| 최대 동시 보유 | 67.00 | 53.00 | -14.00 |
| 회전율 배수 | 22.50 | 12.94 | -9.56 |
| 수수료(원) | 674,997.43 | 388,301.70 | -286,695.73 |
| 슬리피지 영향(원) | 4,499,885.98 | 2,588,763.30 | -1,911,122.68 |

- MDD: CONTROL -36.87% (peak 2023-04-07, trough 2023-10-31, recovery 2026-01-30); 후보 -18.75% (peak 2021-08-09, trough 2022-10-13, recovery 2023-07-25). `CONTROL MDD - 후보 MDD = -18.11%p`; 공식 실패 기준 +5.0%p에 미달해 후보 상대 MDD는 통과야.
- 청산 사유: CONTROL `{'EXIT3_PROGRESSED_TO_EARLY_TREND': 2, 'EXIT3_PROGRESSED_TO_TRANSITION': 6, 'EXIT3_PROGRESSED_TO_WEAK': 5, 'EXIT4_SCORE_DRAWDOWN_GE_15': 117, 'LOSS_GUARD_CLOSE_LE_NEG_15': 284}`; 후보 `{'EXIT3_PROGRESSED_TO_BASE': 1, 'EXIT3_PROGRESSED_TO_EARLY_TREND': 2, 'EXIT3_PROGRESSED_TO_TRANSITION': 6, 'EXIT3_PROGRESSED_TO_WEAK': 3, 'EXIT4_SCORE_DRAWDOWN_GE_15': 85, 'LOSS_GUARD_CLOSE_LE_NEG_15': 136}`.
- 비용: CONTROL 수수료 674,997.43원·슬리피지 4,499,885.98원; 후보 수수료 388,301.70원·슬리피지 2,588,763.30원. 양쪽에서 수수료와 슬리피지 재계산, 정수주, 500만원 포함예산, T+1 매도자금, 현금 보존 검사가 PASS야.
- cutoff 미청산 48/20건은 실현 청산과 분리했고 유효 cutoff mark로만 평가했어. 허구 매도·가상 비용은 넣지 않았어.

### NAV 결측과 최종 integrity readjudication

관측 NAV coverage는 CONTROL 99.86%(1,385/1,387), 후보 99.28%(1,377/1,387)야. 양쪽 최장 연속 결측은 1일이고 전체 NAV 결측은 CONTROL 2일, 후보 10일이야. 세 identity의 adjusted 원천 행은 `HIGH_LT_CLOSE`라 Repository V2 analytic projection이 거부했어. 같은 날 raw 거래행은 있지만 adjusted close를 유효 mark라고 임의 승인할 수 없어서 모든 mark를 UNRESOLVED로 두고 날짜 전체를 NAV/MDD에서 제외했어. 날짜·raw/adjusted hash·OHLC·shares/진입원가 증거는 `unresolved_mark_reconciliation.csv`에 있어.
- 원본 finalizer의 `integrity_audit.json`은 결측 mark가 1건이라도 있으면 MAJOR/CHECK_REQUIRED로 분류했어. 공식 채택 기준 §2 D/E는 coverage ≥90%이면 관측 MDD를 허용하고 valuation gap 자체로 자동 CHECK_REQUIRED하지 않는다고 명시해. P3-1/P3-2 선행 공식 재판정도 같은 유형의 isolated invalid adjusted row를 MINOR로 취급했어.
- 이번 원인은 3 identity·12 group-day에 국한돼 있고 coverage 하락은 90% 기준과 멀어. 별도 구조 오류(신호/PIT, 가격파일 미가용, projection mismatch, 시총, 현금/비용/정산, worker, cutoff entry)는 없어. 이 근거로 raw finalizer 기록은 보존하고 `p2_2_integrity_audit.json`에서 공식 기준에 따라 `PASS_WITH_OBSERVED_NAV`로 재판정했어. 원자료 결측 자체는 지우거나 수치 보정하지 않았어.

### 코엔텍(`029960 / KR7029960002`) 현금 경로와 보유 감사

새 현금 경로로 다시 확인했어. CONTROL에는 signal trade 2건이 있었지만 둘 다 `SKIPPED_CASH_UNAVAILABLE`; 현금 변화는 각각 0원이야. 실제 매수·매도 0건, cutoff 보유 0주, NAV mark 0건이야. 후보는 trade/event 0건이며 3개 필터 감사행은 2건 alignment 거절, 1건 시총 거절이야. 따라서 재생 후 어느 그룹에도 Koentec 보유·정산 노출이 없어. 상세 행은 `koentec_exclusion184_audit.json`과 그룹 원장에 남겼어.

### 182쌍 P2 V02와의 변화

기존 V02는 182쌍 기준이었고 CONTROL coverage 68.85%, 후보 61.86%여서 총수익·CAGR·MDD는 공식 산출 불가였어. 184쌍 재생에서는 CONTROL 99.86%, 후보 99.28%야. CONTROL attempts 2,287→2,283, cash skip 1,829→1,821, 실매수 458→462, 실현 청산 410→414. 후보 attempts 283→282, cash skip 33→29, 실매수 250→253, 실현 청산 228→233, cutoff 미청산 22→20. old outputs로 새 cash path를 추정하지 않고 전체 portfolio를 각각 1회 재생했어. 항목별 차이는 `p2_2_baseline_comparison.csv`에 있어.

## 판정 범위 및 산출물

- P2-2만 재판정했어. `NOT_FINAL_5WINDOW`, 후보 공식 채택 `NOT_EVALUATED`, 기본 전략 승격 `NOT_EVALUATED`; 기본 전략 `PATTERN_A_FAST_FINAL_STRATEGY_V02` 유지.
- 필수 evidence: `exclusion_policy_audit.json`, `p3_1_rejudgment.json`, `p3_2_rejudgment.json`, `p3_1_gate_results.json`, `p3_2_gate_results.json`, `p2_2_gate_results.json`, `p2_2_integrity_audit.json`, `permanent_exclusion_pairs.csv`, 양 그룹 trades/events/cash/NAV/missing marks, `source_manifest.json`, `artifact_hashes.json`, replay/finalizer/adjudication scripts.
- 추가 provenance: raw conservative finalizer outputs `p2_2_finalizer_integrity_audit_raw.json` / `p2_2_finalizer_report_raw.md`; original sealed source snapshots and hash evidence remain in place. `artifact_hashes.json` lists the current research directory files; its own hash is excluded.
