| 레벨 | 개수 | 내용 |
|---|---:|---|
| CRITICAL | 0 | 확인된 CRITICAL 오류 없음 |
| MAJOR | 1 | 실제 체결 진입 집합 차이 64건을 같은 종목의 선행 HWM exit로 추적하지 못해 isolation gate 실패 |
| MINOR | 0 | 무결성 중단으로 최종 성과·성공 gate를 평가하지 않음 |

## 1. 최종 토큰

`FAST_CORE_V2_P3_2_120D_HWM_EXIT_EXPERIMENT_V01_CHECK_REQUIRED`

Candidate C 전체 종목 replay는 완료했지만, 필수 isolation 검증이 실패해 W의 중단 조건대로 여기서 멈췄어. 자동 재실행하지 않았어.

## 2. CONTROL frozen authority 확인

- 이전 완료 토큰: `FAST_CORE_V2_P3_2_FROZEN_PORTFOLIO_AUTHORITY_REPLAY_FIX_V01_COMPLETE`
- 원본 commit: `5fa3696ac3de9b9fa335b384e475be22b9e7a02b`
- CONTROL 입력 5개 파일의 저장 바이트와 Git 객체 hash가 일치했어.
- 기간: 2022-01-03~2026-08-31, 실행 지원 2026-09-01, survivor 2,539개.
- 신규 가격/network 호출 및 latest authority 사용: 0.
- 자료 한계: 원본 2026-09-21 merged PIT bytes가 없어 저장된 survivor projection과 historical PIT interval을 사용했어. 앞선 frozen CONTROL parity를 기준으로 삼았어.

## 3. Candidate C exact rule

V2 진입·re-entry, -15% pre-PROGRESSED guard, Exit 3/4를 그대로 두고, 진입 후 120번째 KRX 보유 세션 EOD부터 completed close 기준 HWM 대비 -20% 하락 시그널을 발생시키며 다음 KRX 세션 시가에 청산하는 연구용 후보야. production/canonical 소스는 수정하지 않았어.

## 4. 거래 단위 전략 지표

최종 비교 지표는 isolation 실패 때문에 확정·보고하지 않았어. 저장된 Candidate C ledger는 438행이고, CONTROL ledger는 405행이야. 행 수만으로 전략 성과 우열을 판단하지 않았어.

## 5. 보유기간 / MFE / MAE

통합 보유기간·MFE·MAE 비교는 중단으로 미보고야. HWM 감사 파일에는 137개 HWM trigger row가 있고, 133개가 거래 청산에 적용됐어. 적용된 exit가 120번째 세션 이후인지 검증은 통과했어.

## 6. 대형 승리 / 대형 손실

CONTROL 대 Candidate C의 대형 승리·손실 비교는 계산 결과를 유효 성과로 인증하지 않았고, 여기서는 미보고야.

## 7. Realistic portfolio 지표

Candidate C portfolio replay 산출물은 저장됐어. isolation guard에 도달하기 전 통과한 구조 검사는 현금 보존 PASS, unresolved position 0, equity curve 1,140행, mcap unresolved 0행이야. 최종 portfolio 성과 지표는 무결성 중단 때문에 보고하지 않았어.

## 8. Lost/gained opportunity 분석

비교용 CSV는 생성됐지만 isolation 검증 전 산출이라 기회비용 원인 분해를 확정 결과로 보고하지 않았어. 특히 portfolio cash 변화에 의한 다른 종목 체결 차이와 종목별 lifecycle 차이를 분리 검증하지 않았어.

## 9. 성공 Gate

Realized win rate, median terminal return, 평균 terminal return 대 CONTROL, portfolio MDD gate를 평가하지 않았어. Candidate C의 성공/실패를 판정하지 않아.

## 10. 공식 V2 변경 추천

추천하지 않아. isolation 검증이 해결되기 전까지 공식 V2 변경, 5-window 확장, threshold sweep, 자동 후속 실험은 진행하지 않아.

## 11. 테스트 / integrity

- Python 문법 검사: PASS.
- `tests/test_p3_2_realistic_portfolio_v01.py`: 4 passed.
- 4종목 smoke: PASS. 첫 진입, 공통 lifecycle, HWM audit 검증 통과.
- Full Candidate C: 2,539/2,539, 10 workers, worker 오류 0, 총 3597.7초.
- Full isolation: 첫 진입 234/234 일치, 공통 거래의 진입/lifecycle 405/405 일치, HWM 영향을 받지 않은 공통 결과 255/255 일치, 후속/missing strategy signal은 HWM lifecycle 변화로 추적 가능.
- 실패 지점: 실제 체결 진입 집합의 64개 차이를 **같은 종목의** 선행 HWM exit로 추적하지 못했어. 실제 체결은 포트폴리오 전체 현금에 좌우되므로 다른 종목의 HWM exit가 현금 경로를 바꿨을 가능성은 있지만, 그 원인은 아직 검증되지 않았어. 따라서 이 상태를 무해한 checker 오탐이라고 단정하지 않아.
- W의 중단 규칙에 따라 추가 replay는 하지 않았어.

## 12. Git status

- 분석 완료 시점 스냅샷: HEAD와 origin/main 모두 `5fa3696ac3de9b9fa335b384e475be22b9e7a02b`였어.
- 이 스냅샷을 작성한 뒤 사용자가 별도로 푸시를 승인했어. 해당 후속 게시 작업의 정확한 commit은 repository history에서 확인할 수 있어.
- 분석 완료 시점의 다른 unrelated research 디렉터리는 untracked였고, 후속 게시 대상에 포함하지 않아.
