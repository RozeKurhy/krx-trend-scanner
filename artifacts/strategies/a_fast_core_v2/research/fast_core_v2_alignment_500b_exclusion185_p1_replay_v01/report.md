# FAST Core V2 Alignment + 500B — 코엔텍 exact pair 제외, 185쌍 P1 replay V01

| 심각도 | 건수 | 설명 |
|---|---:|---|
| CRITICAL | 0 | 무결성 또는 비용/체결 불변식 실패 |
| MAJOR | 0 | P1 공식 A~E에서 CHECK_REQUIRED인 항목 |
| MINOR | 510 | 대상 행 감사와 미해결 평가 mark; 원인은 아래 원장 참조 |

**P1 판정: `PASS_WITH_OBSERVED_NAV`. 5기간 종합: `5WINDOW_GATES_PASS`.** 기본 전략은 그대로 유지하고 후보 승격은 평가하지 않았어.

## 184→185 정책 변경 및 과거 4기간 영향

- 추가한 exact pair는 `029960 / KR7029960002` 1쌍뿐이야. 기존 184쌍 집합은 SHA-256 `5d3bd9a1e27e7e558235f0fba211263cdc90eb0b477978c8338eb019b1a6ec2e`와 동일하고, 새 185쌍 해시는 `c0089f72ed390a2a1df9048d0dac1f309259422e3ff9e77c4f6d986517a5163c`야. 제외 사유는 P1 실제 보유 후 생애주기/기업행위 정산을 확인할 수 없는 데이터 품질 예외이며 성과 기반 제외가 아니야.
- 과거 기준의 P2-1/P2-2/P3-1/P3-2는 저장 원장만 검토했어. 네 기간 모두 최신 184쌍 상태에서 코엔텍 매수 이벤트가 전량 현금 부족 skip이며 `cash_before == cash_after`, 후보 실체결 0건, 미청산 valuation mark 0건이야. 따라서 코엔텍 행만 제거해도 나머지 cash path와 NAV는 그대로고 전 기간 재생은 필요하지 않아.
- P3 원래 V01 산출물에는 코엔텍 매수 행이 있었지만, 이후 데이터 보정 closure와 184쌍 재판정 원장이 해당 산출물을 대체했어. 최신 P3-1/2 closure에서는 해당 시도가 cash skip이고, 연결된 재판정 원장은 비대상 현금 행과 A~E가 변하지 않았음을 기록해. 보고서는 `p3_1_rejudgment.json` 및 `p3_2_rejudgment.json`에 근거했어.
- P2-1/P2-2/P3-1/P3-2 최신 gate는 `p2_1_rejudgment.json` 등 각 원장에 있고, 모두 이전 공식 상태를 유지해. P2/P3 전체 재생은 하지 않았어.

## P1 동결 신호 재사용 및 185쌍 전기간 replay

- 기존 P1 신호평가/필터 재실행은 0회. 184 기준 P1 source manifest 8,996개 중 8,995개 current source hash가 일치했어. 나머지 1개 registry hash 차이는 승인된 exact pair 추가 때문이고, 기준 HEAD blob이 봉인된 184 registry SHA와 일치하며 변경 범위도 해당 pair 1개뿐인 걸 검증했어. 기존 P1 결과 artifact hash 87개는 모두 일치했어. 동결 입력에서는 CONTROL 코엔텍 4행과 후보 filter audit 23행만 제거했고, 후보 trade row 제거는 0행이야.
- 새 공유 유니버스는 정확히 185쌍 제외로 만들었고 eligible ticker/interval 수는 현재 PIT에서 다시 계산했어. 포트폴리오 표본 점검 뒤 3,107 거래일에 대해 CONTROL과 후보를 각각 순차 재생했어. worker error 0건, 재시도 0회였어. 2026-09-01 지원일은 후보 cutoff 미청산 1건의 후속 청산에만 사용했고 P1 평가 구간 지표에는 넣지 않았어.

| 지표 | CONTROL | 후보 ALIGNMENT_MCAP_500B | 후보−CONTROL |
|---|---:|---:|---:|
| 총수익률 % | 66.08 | 107.65 | 41.57 |
| CAGR % | 4.09 | 5.94 | 1.85 |
| MDD % | -49.60 | -32.58 | 17.02 |
| NAV coverage % | 92.34 | 93.27 | 0.93 |
| 진입 시도 | 4,791 | 512 | -4,279 |
| 현금 부족 skip | 4,035 | 61 | -3,974 |
| 실제 진입 | 756 | 451 | -305 |
| 실현 청산 | 703 | 428 | -275 |
| cutoff 미청산 | 53 | 23 | -30 |
| 평균 자본 활용률 % | 94.43 | 57.77 | -36.66 |
| 최대 동시 보유 | 65 | 55 | -10 |
| 수수료 원 | 1,106,118 | 681,301 | -424,817 |
| 슬리피지 원 | 7,373,978 | 4,542,094 | -2,831,884 |
| cutoff NAV 원 | 332,165,861 | 415,303,250 | 83,137,389 |

- MDD 유형/평가: CONTROL `OBSERVED` (coverage 92.34%, 238일 누락), 후보 `OBSERVED` (coverage 93.27%, 209일 누락). 기말 NAV 가능: CONTROL `True`, 후보 `True`.
- 잔여 미해결 valuation mark는 497개 position-date 행(CONTROL 259, 후보 238)이야. NAV 누락일은 중복 종목을 합친 날짜 수로 CONTROL 238일, 후보 209일이야. 전체 ticker/ISU/date 목록은 `p1_unresolved_mark_summary.csv`, 그룹별 원장은 `p1_control_missing_marks.csv`와 `p1_candidate_missing_marks.csv`에 보존했어. 임의 정산/대체/forward-fill은 하지 않았어.

## 공식 P1 A~E 및 산출물 검증

- CONTROL A~E: `['PASS', 'PASS', 'PASS', 'PASS', 'OBSERVED']`.
- 후보 A~E: `['PASS', 'PASS', 'PASS', 'PASS', 'OBSERVED']`. 후보 상대 MDD 악화폭 `CONTROL MDD - Candidate MDD = -17.02%p`, 실패 기준은 +5.0%p 이상이야.
- 현금 부족은 필수 진단이며 PASS/FAIL에 사용하지 않았어. P1에서 남은 CHECK_REQUIRED가 있으면 5기간 결과는 `HOLD`로 남겼고, 추가 영구 제외나 임의 평가 방식 변경은 하지 않았어.
- 해시, 입력 재사용, 비용/현금 보존 상세는 `p1_integrity_audit.json`, `artifact_hashes.json`, `authority_hashes.json`, `source_manifest.json`을 확인하면 돼.

## 5기간 공식 게이트 요약

| 기간 | 상태 | 재생 여부 |
|---|---|---|
| P1 | PASS_WITH_OBSERVED_NAV | P1 full replay |
| P2-1 | PASS_WITH_OBSERVED_NAV | 저장 원장 재판정 |
| P2-2 | PASS_WITH_OBSERVED_NAV | 저장 원장 재판정 |
| P3-1 | PASS_WITH_OBSERVED_NAV | 저장 원장 재판정 |
| P3-2 | PASS_WITH_OBSERVED_NAV | 저장 원장 재판정 |

기본 전략 `PATTERN_A_FAST_FINAL_STRATEGY_V02`는 유지돼. 후보의 공식 채택 또는 기본 전략 승격은 이 실행에서 수행하지 않았어.
