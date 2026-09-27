# Pattern B E/T-only 현실 포트폴리오 최종 심사 V01

최종 판정: `HOLD`

## 5-window 결과

| Window | Net total return | CAGR | MDD | Ending equity | Cash skip | Turnover | Max positions | Unresolved | Gate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| P1 | CHECK_REQUIRED | CHECK_REQUIRED | CHECK_REQUIRED | CHECK_REQUIRED | CHECK_REQUIRED | CHECK_REQUIRED | CHECK_REQUIRED | CHECK_REQUIRED | CHECK_REQUIRED_TAX_AUTHORITY |
| P2-1 | CHECK_REQUIRED | CHECK_REQUIRED | CHECK_REQUIRED | CHECK_REQUIRED | 15.04% | 10.01x | 59.00 | 2,528.00 | A:CHECK_REQUIRED/C:CHECK_REQUIRED/D:CHECK_REQUIRED/E:FAIL/F:CHECK_REQUIRED |
| P2-2 | CHECK_REQUIRED | CHECK_REQUIRED | CHECK_REQUIRED | CHECK_REQUIRED | 24.08% | 13.06x | 63.00 | 3,898.00 | A:CHECK_REQUIRED/C:CHECK_REQUIRED/D:CHECK_REQUIRED/E:FAIL/F:CHECK_REQUIRED |
| P3-1 | CHECK_REQUIRED | CHECK_REQUIRED | CHECK_REQUIRED | CHECK_REQUIRED | 18.72% | 7.76x | 53.00 | 2,009.00 | A:CHECK_REQUIRED/C:CHECK_REQUIRED/D:CHECK_REQUIRED/E:FAIL/F:CHECK_REQUIRED |
| P3-2 | CHECK_REQUIRED | CHECK_REQUIRED | CHECK_REQUIRED | CHECK_REQUIRED | 28.71% | 10.69x | 58.00 | 3,070.00 | A:CHECK_REQUIRED/C:CHECK_REQUIRED/D:CHECK_REQUIRED/E:FAIL/F:CHECK_REQUIRED |

## 필수 성과 진단

아래 거래 진단은 현금 제약을 적용한 포트폴리오에서 effective end까지 실제 청산된 거래 기준이야. 포트폴리오 수익률·CAGR·MDD가 확정됐다는 뜻은 아니야.

| Window | 청산 거래 | 양수 거래율 | 거래 순수익 중앙값 | +30/+50/+100 거래 수 | -30/-40/-50/-60 거래 수 |
|---|---:|---:|---:|---:|---:|
| P2-1 | 165 | 80.00% | 12.78% | 35/14/4 | 8/2/0/0 |
| P2-2 | 226 | 77.43% | 10.78% | 41/17/4 | 15/6/4/2 |
| P3-1 | 126 | 81.75% | 13.53% | 29/11/2 | 7/1/0/0 |
| P3-2 | 184 | 78.80% | 11.13% | 35/14/2 | 12/3/2/1 |

| Window | 평균/중앙값/P90 보유 세션 | 평균/최대 동시 보유 | 평균/최대 현금 활용률* | Turnover | 종료 시 보유 수 |
|---|---:|---:|---:|---:|---:|
| P2-1 | 118.9/43.0/409.2 | 32.8/59 | 20.18%/84.57% | 10.01x | 45 |
| P2-2 | 143.6/43.0/413.0 | 34.2/63 | 20.18%/84.57% | 13.06x | 59 |
| P3-1 | 134.5/44.0/413.0 | 34.1/53 | 15.56%/56.69% | 7.76x | 40 |
| P3-2 | 151.2/44.0/434.0 | 34.4/58 | 15.56%/56.69% | 10.69x | 53 |

| Window | 상위 1종목 이익 비중 | 상위 5종목 이익 기여 | 상위 5종목 손실 기여 | DEEP 도달 진단** |
|---|---:|---:|---:|---:|
| P2-1 | 5.73% | 21.80% | 32.71% | 56건 / 도달 22.76% / 실현 승률 19.23% / median MAE -58.19% |
| P2-2 | 4.65% | 17.92% | 26.92% | 69건 / 도달 19.55% / 실현 승률 19.57% / median MAE -62.70% |
| P3-1 | 6.54% | 21.63% | 38.21% | 50건 / 도달 24.63% / 실현 승률 20.00% / median MAE -56.51% |
| P3-2 | 5.04% | 17.78% | 27.26% | 63건 / 도달 20.32% / 실현 승률 20.93% / median MAE -60.90% |

**연간 equity snapshot(참고·비공식):** P2-1/P2-2 기록값은 2021 +19.52%, 2022 -3.82%; P3-1/P3-2는 2022 +3.98%야. 각 연도 종료 exact equity 연속성이 확보되지 않아 연간 수익률로 확정할 수 없고, 2023년 이후 snapshot은 저장되지 않았어.

* exact 일별 valuation gap이 있어 평균/최대 현금 활용률은 관측 진단값이며 공식 완결 값이 아니야. 보유 기간·거래 수·turnover·동시 보유 수는 체결 이벤트 기준이야.

** DEEP 진단은 저장된 candidate lifecycle 요약이야. 포트폴리오가 실제 보유한 종목의 DEEP 도달/청산 성과로 해석하면 안 돼.

**종료 시 보유 수**는 effective-end 일자의 portfolio daily ledger에서 읽었어. 네 window 모두 그 날짜 aggregate exact market value와 ending equity가 비어 있어 official return/CAGR/MDD는 CHECK_REQUIRED로 유지했어.

## Gate A–F

- Gate A: `CHECK_REQUIRED`
- Gate B: `CHECK_REQUIRED`
- Gate C: `CHECK_REQUIRED`
- Gate D: `CHECK_REQUIRED`
- Gate E: `FAIL`
- Gate F: `CHECK_REQUIRED`

Exact-valuation audit에서 일별 equity 공백과 종료 equity 미해결을 확인해, 영향 window의 net return/CAGR/MDD를 수치로 확정하지 않았어.
## 비용 authority

P1은 기존 trade ledger에서 2014–2020 realized exit 211건을 확인했고, 그중 세율 누락은 211건이야. Repository 검증 세율표는 2021-01-01부터라서 해당 연도 세율을 추정하지 않았고, P1 포트폴리오 replay를 수행하지 않았어. 이 누락은 P1 cash allocation과 equity 경로에 영향을 주므로 최종 판정은 HOLD야.

## Lifecycle replay 근거

다섯 창의 저장 stage audit에서 pass 신호와 trade ledger가 1:1로 연결되는지 검사했어. pass 신호 중 baseline position 때문에 억제된 건 0건이었고, 기간 종료 후 진입 시점이어서 미체결된 신호만 포트폴리오 attempt에서 제외했어. 각 cash skip마다 후속 pass 신호 목록을 `cash_skip_lifecycle_audit.csv`에 연결했어.

저장된 결과 파일 해시는 모두 당시 metadata와 일치해. 실행 당시 study orchestrator 파일은 시작 HEAD에서 untracked였고 기록 SHA는 현재 커밋본과 다르다. candidate runner 및 Pattern B signal generator는 시작 HEAD 이후 바뀌지 않은 것으로 확인했으며, orchestrator 출처 차이는 Gate A에 CHECK_REQUIRED로 남겼어.

## 추가 replay 여부

P2-1 첫 포트폴리오 시도는 입력 정규화 단계에서 NaN terminal date 처리 오류로 끝났고 cash/equity replay 및 window 산출물 생성 전이었다. 빈 날짜를 None으로 정규화한 뒤 한 번 수정 실행했어. 이전 실패 시도 결과를 재사용하지 않았어.

## 판정

후보 규칙은 변경하지 않았어. P2/P3의 결과는 window별 지표와 audit에 있으며, P1의 역사 세율 authority가 불완전해 여섯 gate의 5-window 종합 통과 여부를 확정할 수 없어 `HOLD`야.

## 산출물

- `execution_contract.json`, `preflight.json`, `five_window_summary.csv`, `portfolio_metrics.csv`, `portfolio_metrics.json`, `official_adoption_gates.csv`, `official_adoption_gates.json`, `summary.json`
- window별 portfolio event, daily equity, skipped entry, cost, cash, valuation, attempt, cash-skip lifecycle audit
- 기존 trade ledger 재복사 없음; 입력 경로와 SHA-256은 `metadata.json`에 저장
