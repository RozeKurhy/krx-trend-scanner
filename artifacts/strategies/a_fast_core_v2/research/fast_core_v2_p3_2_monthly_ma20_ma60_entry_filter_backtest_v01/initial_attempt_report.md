# P3-2 월간 MA20 / MA60 신호 종가 진입 필터 백테스트

| 레벨 | 개수 | 내용 |
|---|---:|---|
| CRITICAL | 0 | Authority/PIT/CONTROL parity 불일치 없음. |
| MAJOR | 1 | Signal-close parity 계산 중 연구 스크립트 오류로 중단. MA20/MA60 후보 재생은 시작하지 않음. |
| MINOR | 1 | 코드 오류 수정 및 정적 구문 검사 통과. 지시서의 자동 재실행 금지에 따라 명시 승인 대기. |

## 1. 최종 토큰

`FAST_CORE_V2_P3_2_MONTHLY_MA20_MA60_ENTRY_FILTER_BACKTEST_V01_CHECK_REQUIRED`

## 2. Authority / PIT

- Frozen P3-2 CONTROL 405건의 원장/이벤트/equity 파일 해시가 이전 고정 snapshot 및 현재 HEAD blob과 일치했어. 저장 CONTROL의 전략·포트폴리오 parity는 PASS야.
- 기간 2022-01-03~2026-08-31, execution support 2026-09-01, survivor identity 2,539개. 요청 worker는 10개야.
- canonical V2/P3-2 runner 소스와 historical PIT/calendar 해시 검증이 통과했어. CONTROL 전체 재생 및 최신 rolling authority 접근은 없었고 네트워크/API/가격 수집 호출은 0회야.

## 3. 신호 종가 vs 다음 날 시가 분류

요청된 405건 비교 도중 missing-history 분류 코드에서 `PeriodIndex.le()` API 오류가 발생했어. 비교 CSV와 분류 수치는 완성되지 않았어. entry_open을 후보 필터에 사용한 일은 없고 MA 후보 replay도 시작하지 않았어.

## 4. 후보 규칙 / 5~9. 결과

MA20·MA60 규칙은 작성했지만 A/B 전략 및 현실 포트폴리오 replay는 실행하지 않았어. 차단 거래, 후속 거래, 실제 portfolio opportunity cost 결과도 아직 없어.

## 10. 성공 Gate / 11. 후속 5-window 검증

평가할 후보 결과가 없어 Gate 판정 및 5-window 추천을 보류해. P3-2 단일 구간으로 공식 전략 승격은 없고, production/canonical 파일도 수정하지 않았어.

## 12. 검증 상태

- `preflight.json`: saved CONTROL/hash/source/authority 검증 요약.
- `failure.json`: 중단 단계 및 재실행 금지 표시.
- 수정한 replay script의 Python 정적 구문 검사는 PASS. 후보 backtest integrity checks는 미실행.
- 지시서에 “자동 재실행 금지”가 있어 수정 후 전체 실행은 파트너의 명시 지시 전까지 보류해.

## 13. Git

- 실행 시작 HEAD와 origin/main은 동일했고 현재도 ahead/behind 0/0이야.
- 후보 결과가 없어서 commit/push는 하지 않았어. 완료된 후보 분석 산출물을 얻은 뒤 지시서 범위만 stage/commit/push할게.
