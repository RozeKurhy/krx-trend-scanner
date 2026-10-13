## 이슈 건수 및 최종 판정

| 등급 | 건수 | 내용 |
|---|---:|---|
| CRITICAL | 0 | 데이터·PIT·identity 또는 운영 설정의 불일치 없음 |
| MAJOR | 0 | Phase4C, 웹 전체 suite, 관련 회귀 gate 모두 완료·통과 |
| MINOR | 1 | 전체 Phase4C peak RSS가 약 10.9GB로 높고, 완료까지 약 6분 22초가 걸림 |

**최종 판정: `IMPLEMENTATION_STAGING_PASS` 권고.** 이 판정은 staging 검증 통과만 뜻해. 운영 활성화, 적용일 지정, canonical/static 발행, commit/push, 배포는 수행하지 않았어.

## 작업 범위와 보존 상태

- 기준일: 2026-10-13 KST
- 기준 HEAD 및 종료 HEAD: `a3a2a7ab9f634633760eb4992630608d0280e843`
- 기준 `origin/main` 및 종료 `origin/main`: `a3a2a7ab9f634633760eb4992630608d0280e843`
- 시작 시 worktree에는 선행 작업의 tracked/untracked 변경이 있었어. 이 변경을 초기화하거나 삭제하지 않았고, 새 코드는 `scripts/export_strategy_monitor_web.py`의 B Select history helper에만 추가했어.
- 이번 보고서는 별도 신규 경로에 작성했어. 다른 기존 보고서와 연구 산출물은 덮어쓰지 않았어.
- `web/data/`와 `artifacts/reporting/stock_reports/`의 변경은 0건. 임시 Phase4C 및 historical-authority staging 경로도 남지 않았어.
- 공식 5기간 백테스트, 신호 재생, 실제 Daily Update, canonical/static 발행, 배포, 주문은 수행하지 않았어.

## 병목 및 최소 변경

### 동일 입력 기준

- Frozen authority: `artifacts/strategies/b_select_core_v1/production/20260925/status.json`
- `target=2026-09-25`, `reference=2026-09-23`
- 1,451 COMMON items, 312 history trades(REALIZED 288, OPEN 24), 248 tickers
- 열린 거래는 현재가·평가일 등 값이 모두 존재하는 24건이었어.

### 원인

`frame_covers()`가 거래마다 DataFrame 전체를 `frame.loc[index]`로 행 변환했고, coverage를 통과한 거래에서도 같은 행 사전을 다시 만들었어. pandas의 row Series 생성은 DataFrame attrs를 복사했고, attrs 안의 `session_projection_audit`가 거래·행마다 반복 복사됐어. 이전 시도 traceback은 이 경로의 `copy.deepcopy(other.attrs)`까지 도달했어.

기준 helper 계측에서 `frame.loc` 호출은 총 340,786회였어. 그중 반복 coverage 검사 176,737회, coverage 뒤 재변환 164,001회, OPEN exact-session 구간 48회였어. 기준 helper 계측 실행은 원본 attrs를 임시로 비워 이 반복 복사 비용을 억제한 진단 모드였으므로, 그 165초를 실제 무수정 실행시간으로 해석하지 않아.

### 수정

동일한 조회 프레임의 행을 `to_dict(orient="index")`로 한 번만 날짜별 사전으로 변환해 coverage와 지표 산출에서 공유하게 했어. 변환은 broad ticker frame 248회, trade fallback frame 8회, OPEN exact-session frame 48회로 총 304회야. 반복 `DataFrame.loc` 변환은 제거했어. 프레임의 projection audit은 원본 DataFrame attrs에서 계속 검사하고, 필요한 high/low/open/close 유효성·raw/adjusted 날짜·PIT identity·정확한 거래일 검사는 그대로 유지했어. 누락/중복 날짜는 coverage 실패로 남아 임의로 보충하지 않아.

### 같은 입력 출력 대조

- 기준 output SHA-256: `8c4412308a4ce4eb28ba0d198aac05ac2ded87fe6fd0f3f3f105c1e6e5db3110`
- 수정 후 output SHA-256: 동일
- 거래 순서와 312개 객체 비교: `equal=True`
- OPEN history: 24건 모두 `latest_close`, `latest_close_as_of`, `current_return_pct`, `holding_age_sessions` 유지
- 000370 continuity: report와 Strategy Monitor 모두 `OPEN`, 전략 ID `PATTERN_A_FAST_FINAL_STRATEGY_V02`. Phase4C 테스트 assertion 통과.

## 단계 계측

Phase4C `test_real_run_status_pass`의 최종 진단 계측은 다음과 같아.

| 단계 | 시간 |
|---|---:|
| Stock Report payload | 23.74초 |
| Market ranking | 0.27초 |
| Strategy Monitor | 142.47초 |
| Sector RS | 0.51초 |
| Foreign net buy ranking | 168.49초 |
| Health | 46.18초 |
| 전체 `run_phase4c()` 벽시계 | 382.29초 |
| 전체 suite | 393.16초 |

- 이전 V02 closeout의 불완료 실행에서는 Strategy Monitor가 398.56초까지 진행했고 suite는 423.34초에 중단됐어. 수정 후 동일 historical target fixture의 Strategy Monitor는 142.47초에 끝났어(약 64% 단축). 이전 실행은 끝까지 완주하지 않았으므로 suite 전체시간끼리 성능 비교하지 않아.
- 최종 fixture의 `stock_report_web.copy.deepcopy`는 17,844회 / 0.23초였어. 관측된 병목은 deepcopy 횟수 자체가 아니라 pandas Series 생성 시 대형 projection attrs의 반복 복사였어.
- 진단 fixture RSS high-water mark: 시작 127.41MB, 종료 peak 10,916.44MB. 이전 중단 실행의 3,757.05MB는 후속 ranking/health 단계 전 값이므로 직접 비교 가능한 peak가 아니야. 이번 전체 fixture는 완료됐지만 peak 메모리는 후속 용량 계획에서 고려해야 해.

helper 격리 진단(수정 전, attrs deepcopy를 임시 회피한 측정)에서는 Repository V2 생성 126.77초, PIT/calendar 검증 1.48초, rolling authority/calendar load 약 0.07초, `get_daily` 304회 / 7.38초 / 단일 호출 최장 0.082초였어. 호출은 broad 248회, per-trade fallback 8회, OPEN exact-session 48회였고 fallback 외 `get_daily` 호출은 없었어. raw index build는 전체 저장소 scan 1회, 11,384 partition file, 89,333 반환 행, index 메모리 약 1.30GB였어. 이 수치는 attrs 복사 비용을 억제한 진단 실행이라 수정 후 end-to-end 시간과 직접 비교하지 않아.

## 테스트 및 검증

| 검증 | 결과 |
|---|---|
| `tests/test_daily_update_phase4c_v01.py` 전체 real-corpus suite | **34 passed, 393.16초** |
| 단계 진단용 `test_real_run_status_pass` | **1 passed, 382.61초**; 000370 OPEN 및 stage/RSS 출력 확인 |
| `tests/test_web_strategy.py` 전체(clean-exporter projection 포함) | **26 passed, 586.14초** |
| 관련 V2 reentry·stock-report golden·500B gate·Phase4B·Phase4D·V2 contract 회귀 | **160 passed, 69.68초** |
| Web 빠른 나머지 검사 | **25 passed, 1 deselected, 0.75초**; slow projection은 위 전체 웹 suite에서 실행·통과 |
| `py_compile` (`scripts/export_strategy_monitor_web.py`) | PASS |
| `node --check` (`web/js/strategy.js`, `web/js/report.js`) | PASS |
| promotion config JSON parse | PASS |
| 영구 제외 정책 검증 | **185 identity pairs**, SHA-256 `c0089f72ed390a2a1df9048d0dac1f309259422e3ff9e77c4f6d986517a5163c` 일치 |
| `git diff --check` | PASS |
| phase4c temp/staging 정리, 발행 데이터 무변경 | PASS; temp 경로 없음, `web/data/`·canonical stock reports 변경 0건 |

관련 회귀 테스트는 기존 pandas timedelta deprecation 및 특성 계산 overflow 경고를 출력했지만 실패는 없었어. 이번 helper 변경 파일에서 발생한 테스트 실패는 0건이야.

## 설정 및 남은 비용

- 운영 config는 `enabled=false`, `effective_signal_date=PENDING_USER_APPROVAL`, `operational_activation_approved=false`로 유지돼.
- Strategy Monitor 병목은 제거됐고 관련 데이터 parity gate를 통과했어. 전체 real-corpus 실행은 완료됐어.
- 남은 관찰 사항은 완료 fixture peak RSS 10.9GB와 Phase4C/web 전체 suite 실행시간이야. 단계 계측상 나머지 큰 시간은 Foreign net buy ranking 168.49초와 Health 46.18초에 있었어. 이 작업 범위 밖의 최적화로 확장하지 않았어.
- 새 커밋이나 push는 하지 않았고 `HEAD == origin/main` 상태를 유지했어.
