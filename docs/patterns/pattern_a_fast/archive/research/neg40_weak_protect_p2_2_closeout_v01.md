# NEG40 / WEAK Protect — P2-2 최종 연구 마감 V01

작성일: 2026-09-24 KST
상태: `P2_2_CLOSED` / 결과 검증 `P2_2_CERTIFIED_PASS`

## 목적과 범위

CONTROL `PATTERN_A_FAST_FINAL_STRATEGY_V02`와 Candidate
`PATTERN_A_FAST_CORE_V2_NEG40_WEAK_PROTECT_SOFT_EXIT_V01`의 P2-2 동일 진입
비교를 마감한다. 추가 백테스트, P1/P3, threshold·전략 규칙 변경은 수행하지
않았다.

- 평가 기간: 2021-01-04 ~ 2026-08-31
- execution support: 2026-09-01
- 최종 run: `artifacts/backtests/p2_2_neg40_weak_protect_v01/run_20260924_final_corrective_v01/`
- 이전 `run_20260923`은 삭제하지 않았다. 최종 교정 run을 P2-2의 authoritative result로 사용한다.
- 전체 계산: 8 workers, 2,739 tickers, 2,748 identity segments, 1,397 tickers with entries
- 실제 처리 4,110.038초, setup 130.917초, ticker 오류 0
- identity authority SHA-256: `9997c55526575bc2341b7ce2e056def1d0a8c3fb77d89c8fadb3716ae2f46dd4`; coverage는 2010-01-04 ~ 2026-09-01

## 수정 계약

- P2-2 PIT identity authority extension의 manifest, 데이터 파일 checksum, content digest, historical overlap, 기간·coverage를 검증한다. 전체 coverage는 execution support인 2026-09-01까지 요구한다.
- 매칭·중복 검증의 기준 키는 `pair_id`다. CONTROL/Candidate pair 집합과 pair별 원본 `trade_id`를 보존한다.
- signal cutoff는 `min(window effective end, exact identity effective_to)`로 제한한다. identity 종료 뒤 signal/실행을 생성하지 않는다.
- lifecycle settlement는 정확한 ticker·ISU code·market·identity interval이 일치하는 확인된 KRX KIND 증거에만 적용한다. settlement 전에 정상 market exit가 먼저면 기존 exit를 유지한다.
- synthetic OPEN, nearest-date 대체, forward-fill, 다른 identity 가격 연결, last-close 자동 settlement를 금지한다.
- execution을 확인할 수 없는 signal은 `UNEXECUTED_SIGNAL`로 fail-closed한다. 결과를 성공으로 간주하지 않는다.
- 전략 규칙과 -40% threshold, WEAK 기준, 기간, 필터는 변경하지 않았다.

## 최종 검증

- CONTROL/Candidate matched 거래: 각 2,424건
- `pair_id`: 2,424개 고유, 양쪽 집합 동일; pair별 source `trade_id` 동일
- `UNEXECUTED_SIGNAL`: 양쪽 0; Candidate execution support 누락 0
- 010420 / `KR7010420008` / `010420_02`: 양쪽 `LIFECYCLE_SETTLED`, 2025-09-08, 1,900원, `SHARE_EXCHANGE_CASH_SETTLEMENT`; execution support missing=false, terminal valuation at cutoff=false
- 010420의 2025-09-30 phantom signal: 0건
- `SOFT_EXIT_SIGNAL`: 48건, 48건 모두 next-session execution date와 OPEN 존재. 2026-08-31 신호는 048830의 2026-09-01 OPEN 1,018원으로 실행됨.
- cutoff 뒤 soft event 0건, soft-event 중복 0건, replay consistency PASS
- 모든 ledger aggregate가 full ledger 재집계와 일치하고 lifecycle provenance PASS

## 성과

| 지표 | CONTROL | Candidate |
|---|---:|---:|
| 거래 수 | 2,424 | 2,424 |
| positive count / rate | 745 / 30.7343% | 739 / 30.4868% |
| mean terminal return | 7.9321% | 7.7792% |
| median terminal return | -15.16% | -15.19% |
| OPEN_AT_CUTOFF | 221 | 199 |
| holding days mean / median | 150.955 / 82 | 142.1209 / 82 |
| <= -30% / -40% / -50% / -60% | 57 / 37 / 22 / 13 | 72 / 45 / 9 / 4 |
| >= +30% / +50% / +100% | 462 / 336 / 134 | 457 / 333 / 134 |

Paired delta mean은 -0.153%p, median은 0.0%p이며 improved / worsened / same은
25 / 23 / 2,376이다. Post-PROGRESSED -40 touch 61 trades, WEAK Protect 26
trades 및 3,725 EOD events, SOFT signal/incremental exit 각 48건이다. >=+50%
winner damage 3건, >=+100% winner damage 0건. CONTROL 대비 deep-tail 개선 거래는
-40/-50/-60 기준 5/13/10건이지만, 전체 <=-40% 거래는 Candidate 45건 대
CONTROL 37건으로 Candidate가 8건 더 많다.

연구 해석은 **P2-1과 부분 일치**다. Deep-tail protection 방향은 재현됐지만 평균
paired return 개선은 재현되지 않았다. 두 window의 모집단은 별개다. 이 결과만으로
공식 전략 채택 또는 기본 전략 변경을 하지 않는다.

## 이전 P2-2 결과와 diff

이전 `run_20260923`과 최종 run의 `pair_id` 집합은 모두 2,424개로 동일하다. 기존
ledger와 최종 ledger의 공통 컬럼 비교에서 변경 pair는 `010420_02` 1건이다.
이전에는 CONTROL이 `OPEN_AT_CUTOFF`, Candidate가 `UNEXECUTED_SIGNAL`이었고,
Candidate에 2025-09-30 phantom exit가 기록됐다. 최종 결과에서는 양쪽 모두 근거가
있는 2025-09-08 cash settlement로 처리됐다. 나머지 pair는 공통 컬럼상 변동이
없다. 이전 `CHECK_REQUIRED` run은 보존하며 최종 결과로 대체하지 않고, 최종
교정 run만 authoritative P2-2 결과로 지정한다.

010420 settlement 증거는
[`p2_2_lifecycle_settlement_evidence_v01.json`](../../../../strategies/p2_2_lifecycle_settlement_evidence_v01.json)에
보존한다. 근거는 KRX KIND의 2025-08-13 공시 자료와 보조 공시다.

## Missing fixture 상태

`tests/test_adjusted_price_identity_boundary_correction_fix01.py`가 참조하는 다음
파일 3개는 기준 HEAD `90b2d523d37e0281a28abe243c1d1a2aaa18b592`에도 없고 현재
workspace에도 없다.

- `artifacts/data/end_to_end_data_parity/v01/adjusted_price_identity_boundary_correction/fix01/446840/corporate_identity_authority.json`
- `artifacts/data/end_to_end_data_parity/v01/adjusted_price_identity_boundary_correction/fix01/446840/source_vs_identity_semantics.json`
- `artifacts/data/end_to_end_data_parity/v01/adjusted_price_identity_boundary_correction/fix01/blast_radius/identity_candidate_summary.json`

해당 test 파일 자체는 기준 HEAD와 동일하며 fixture 경로도 HEAD tree에 없다. 따라서
세 `FileNotFoundError`는 이번 P2-2 변경으로 fixture가 삭제된 회귀가 아닌
**`KNOWN TEST INFRA GAP`**이다. 새 fixture를 만들거나 보호 파일을 변경하지 않았다.

## 테스트와 산출물

- P2-2 focused suite: 31 PASS (`tests/test_fastcore_neg40_weak_protect_p2_1.py`, `tests/test_standard_backtest_windows.py`)
- `py_compile`: PASS; `git diff --check`: PASS
- 위 missing-fixture suite의 3건은 기준 HEAD에도 파일이 없는 `KNOWN TEST INFRA GAP`
- 실행 산출물 `p2_2_matched_trades.csv`, `p2_2_soft_events.csv`, `p2_2_summary.json`, `summary.json` 및 PIT extension은 기존 artifact 정책에 따라 로컬 보존하며 이 closeout commit에는 포함하지 않는다.
- commit/push에는 P2-2 runner, 해당 focused tests, settlement evidence, 본 closeout 문서와 문서 안내 링크만 포함한다. 무관한 local changes와 untracked artifacts는 유지한다.
