# B Select Core V1 펀더멘탈 상태 UI 통합 V01 결과

| 레벨 | 개수 | 내용 |
|---|---:|---|
| CRITICAL | 0 | 없음. 전략 신호, 버킷 건수, B Select 항목 값은 바뀌지 않고 `fundamental_status` 필드만 추가됨 |
| MAJOR | 1 | **원천 공시 목록 분류 결함 발견.** 해외 상장사(KT, POSCO홀딩스, SK, SK텔레콤, 한국전력, LG디스플레이 등 7종목)의 "해외증권거래소등에신고한사업보고서등의국내신고"를 FilingRegistry가 **접수 연도의 사업보고서(Q4)** 로 분류함. 이 때문에 "최신 분기"가 존재할 수 없는 분기(예: 9월 시점의 당해 Q4)로 잡힐 수 있음. UI helper에는 좁은 보정을 넣었고, 원천 분류기는 수정하지 않음. 지난 V03/FIX01/V04 백테스트에서는 이 문제로 POSCO홀딩스 2026-06-30 신호 1건이 UNAVAILABLE이 됨(P1·P2-2·P3-2) |
| MINOR | 2 | ① 12월이 아닌 결산월 회사(9종목)는 원천의 회계연도 표기가 일정하지 않아 위 보정을 적용하지 않음. 이번 기준일에는 영향 0건 ② 기준 HEAD에서 이미 실패하던 웹 테스트 1건(`test_web_market_ranking`의 report.js 버전 고정값 불일치)을 캐시 버전 변경과 함께 바로잡음 |

## 1. 수정 파일

| 파일 | 변경 |
|---|---|
| `src/trend_scanner/strategies/b_select_core_fundamental_status.py` | **신규**. 공통 펀더멘탈 상태 판정 helper |
| `scripts/export_strategy_monitor_web.py` | B Select 항목에 `fundamental_status` 추가 (+13줄) |
| `web/data/strategy-monitor.json` | 다시 생성. B Select 1,451개 항목에 `fundamental_status`만 추가 |
| `web/strategy.html` | 펀더멘탈 필터 드롭다운 추가(정렬 왼쪽). CSS·JS 캐시 버전 `web-b-select-fundamental-v1` |
| `web/js/strategy.js` | 펀더멘탈 열, 필터 상태와 동작, 건수 집계 |
| `web/js/report.js` | 현재 판단 카드의 B Select 문구에 상태 단어 삽입 |
| `web/report.html` | report.js 캐시 버전 |
| `web/css/app.css` | B Select 행 그리드에 좁은 열 1개 추가, 필터·정렬 정렬 보정 (2줄) |
| `tests/test_b_select_core_fundamental_status.py` | **신규** 8개 테스트 |
| `tests/test_web_strategy.py`, `test_web_stock_report.py`, `test_web_market_ranking.py` | 버전·그리드 고정값만 갱신 |
| `artifacts/reporting/b_select_fundamental_status_ui_v01/` | 렌더 확인 스크린샷 4장 + `results.json` |

커밋: `b0cf439f6` (push하지 않음)

## 2. 공통 펀더멘탈 상태 판정 구조

```
production Fundamentals 산출물 (artifacts/fundamentals/production/{기준일}/tickers/{ticker}.json)
  └ f2.quarters (canonical periodization 관측값) + f2.periodization_builds.anchor_selections (기준일까지 접수된 정기보고서)
      └ evaluate_signal()  ← V03 FIX01과 같은 판정기: 최신 공개 분기 1개, PIT, 이전 분기로 넘어가지 않음, fail-closed
          └ classify_fundamental_status() → 우수 / 양호 / 보통 / 주의 / 미상
              └ export_strategy_monitor_web.py: B Select item["fundamental_status"]
                  ├ 전략 운용 리스트 펀더멘탈 열
                  ├ 전략 운용 펀더멘탈 필터
                  └ 종목 리포트 현재 판단 카드 (같은 strategy-monitor.json 항목을 읽음)
```

- **판정 위치는 한 곳**: 상태 판정은 helper 한 곳에서만 합니다. 화면 세 곳은 같은 JSON 필드를 읽기만 하고 다시 계산하지 않습니다.
- **판정 규칙** (우선순위 순)

  | 상태 | 조건 |
  |---|---|
  | 우수 | 현재 ≥ 20억, 전년동기와 비교 가능, 현재 > 전년동기 |
  | 양호 | 0 < 현재 < 20억, 전년동기와 비교 가능, 현재 > 전년동기 |
  | 보통 | 현재 > 0 이고 위 두 조건에 해당하지 않음 (전년동기 없음, 비교 불가, 같거나 감소 포함) |
  | 주의 | 현재 ≤ 0 |
  | 미상 | 현재 영업이익을 판정할 수 없음 (산출물 없음·불일치, 금융회사, 최신 분기 READY 아님, 비표준 context fail-closed 등) |

  "비교 가능"은 전년동기 값이 READY이고 회계 기준·통화가 같은 경우입니다. 판정할 수 없는 경우는 `주의`로 넣지 않고 반드시 `미상`으로 둡니다.
- **원천 데이터**: Stock Report가 쓰는 같은 날짜의 production Fundamentals 산출물을 읽습니다. OpenDART 호출이나 재수집은 하지 않습니다.
  - 결과 검증: helper가 고른 최신 분기와 현재 영업이익 값은 production `f5_ready`의 최신 분기·분기 영업이익과 1,451종목 모두 일치합니다(값 불일치 0 / 1,432건 비교, 최신 분기 불일치 0건).
- **MAJOR 보정**: 12월 결산 회사에서 회계연도 Y의 사업보고서(11011)가 같은 해 Y 안에 접수된 경우는 "최신 분기" 후보에서 뺍니다.
  - 12월 결산 사업보고서는 항상 다음 해에 접수되므로, 결함 패턴만 정확히 걸러냅니다.
  - 보정 전에는 5종목(KT, POSCO홀딩스, SK, SK텔레콤, 한국전력)이 `미상`이었고, 보정 후에는 각각 보통·우수·우수·우수·보통입니다.

**기준일 2026-09-25 분포** (B Select 1,451종목)

| 우수 | 양호 | 보통 | 주의 | 미상 |
|---:|---:|---:|---:|---:|
| 801 | 176 | 431 | 29 | 14 |

`미상` 14건 사유: 금융회사 11, Q4 단독값 산출 불가 2, 비표준 context fail-closed 1.

## 3. 전략 운용 리스트 변경

- **열 위치**: B Select Core V1 행에 `펀더멘탈` 열을 넣었습니다. 순서는 Pattern A → Pattern B → 펀더멘탈 → 현재가입니다.
- **셀 내용**: 설명 없이 단어 하나(우수/양호/보통/주의/미상)만 표시합니다.
- **다른 전략**: A FAST Core V2와 Julia V1 리스트는 바뀌지 않았습니다(열과 필터 모두 없음).

## 4. 필터 추가

- **위치와 옵션**: 정렬 드롭다운 왼쪽에 `펀더멘탈` 드롭다운을 넣었습니다. 옵션은 전체/우수/양호/보통/주의/미상이고, 기본값은 전체입니다.
- **적용 범위**: B Select Core V1을 선택했을 때만 표시되고 적용됩니다.
- **동작**: 선택한 상태와 정확히 일치하는 행만 보여주고, `전체`를 고르면 해제됩니다.
- **다른 기능과 조합**: 검색, 판단 버킷 필터(보유 유지/관찰 중 등), 보유 정렬(진입일·수익률·이름)과 함께 쓸 수 있습니다. 버킷별 건수도 필터를 반영합니다.

## 5. 현재 판단 카드 변경

- **변경 전**: `B Select Core V1 관찰`
- **변경 후**: `B Select Core V1 우수.관찰` / `양호.관찰` / `보통.관찰` / `주의.관찰` / `미상.관찰`
  - 보유 중인 종목은 `보통.보유`처럼 기존 상태 앞에 상태 단어가 붙습니다.
- **바꾸지 않은 것**: 설명 문구, 영업이익 숫자, YoY 숫자는 넣지 않았고, 카드 추가나 레이아웃 변경도 없습니다. 상단 현재 판단 카드와 하단 전략 카드가 같은 함수를 씁니다.

## 6. 1라인 유지 확인

headless Chrome(DevTools 프로토콜)으로 실제 페이지를 띄우고 B Select 1,451개 행을 모두 측정했습니다.

| 화면 폭 | 행 수 | 2단 배치 행 | 가로 넘침 | 펀더멘탈 셀 줄바꿈 |
|---:|---:|---:|---:|---:|
| 1440px | 1451 | 0 | 0 | 0 |
| 1280px | 1451 | 0 | 0 | 0 |
| 1024px | 1451 | 0 | 0 | 0 |
| 980px | 1451 | 0 | 0 | 0 |

- **새 열 크기**: 펀더멘탈 열은 `minmax(44px, 0.55fr)`입니다. 대신 종목명 열의 최소 폭을 190px에서 170px로, 열 간격을 12px에서 10px로 소폭 줄였습니다.
- **좁은 화면**: 960px 이하의 기존 반응형 배치(3열·2열 그리드)는 원래 설계 그대로입니다.

## 7. 테스트 결과

| 범위 | 결과 |
|---|---|
| 신규 `test_b_select_core_fundamental_status.py` (w.md §9의 1~9, 13, 14, 분류 결함 보정) | 8개 통과 |
| V03 판정 규칙 `test_b_select_core_oi_1q_v03.py` | 14개 통과 |
| 웹 `test_web_strategy.py`, `test_web_stock_report.py`, `test_web_market_ranking.py` | 통과 (변경 전 1개 실패 → 변경 후 0개) |
| B Select `test_b_select_status_v1.py`, `test_b_select_core_v1.py` | 통과 |
| 위 합계 | **85개 통과** |
| 일일 업데이트 Phase4C/4D/4E (`test_daily_update_phase4{c,d,e}_v01.py`) | 변경 전 74 통과 → **변경 후 74 통과** |
| 렌더 확인 (§9의 10~13) | 아래 참조 |

전체 백테스트와 전체 pytest는 실행하지 않았습니다.

**렌더 확인 상세** (`artifacts/reporting/b_select_fundamental_status_ui_v01/results.json`)

| 확인 항목 | 결과 |
|---|---|
| 필터 6개 옵션 | 전체/우수/양호/보통/주의/미상 |
| 필터 위치 | 정렬 드롭다운 왼쪽 |
| 옵션별 표시 건수 = JSON 집계 | 1451 / 801 / 176 / 431 / 29 / 14 모두 일치. 표시된 값도 선택 상태 하나뿐 |
| 정렬 + 필터 조합 ("보유 유지" + "수익률 순" + "우수") | 7건이 수익률 순(+65.36% → −29.28%)으로 나옴. JSON의 보유·우수 7건과 일치 |
| A FAST 전략으로 전환 | 필터 숨김, 펀더멘탈 열 0개 |
| 리포트 카드 = 리스트 값 | 5개 상태 + 보유 종목 1개 직접 확인. `095570` 우수.관찰, `037370` 양호.관찰, `079810` 보통.관찰, `002460` 주의.관찰, `900290` 미상.관찰, `001380` 보통.보유 |

## 8. 전략 결과 무변경 확인

- **JSON 비교**: 다시 생성한 `strategy-monitor.json`에서 `fundamental_status`를 빼면, 변경 전 파일과 **완전히 같습니다**(세 전략 모두).
- **건수**:
  - B Select 버킷 건수는 그대로입니다(entry 0, hold 23, exit 1, watch 1,275, unavailable 152).
  - 거래 이력(312건)과 항목 수(1,451)도 그대로입니다.
- **신규 테스트로 확인**: B Select 항목에서 `fundamental_status`를 뺀 값이 production `status.json` 항목과 정확히 같습니다.
- **바꾸지 않은 것**:
  - 전략 규칙과 진입 자격(`b_select_core_v1.py`), 공식 전략 ID, `build_b_select_core_v1_status.py`
  - 자동 진입·제외, TEST20 승격

## 9. 스크린샷

`artifacts/reporting/b_select_fundamental_status_ui_v01/`

| 파일 | 내용 |
|---|---|
| `strategy_b_select_1280.png` | B Select 리스트 1280px (펀더멘탈 열, 필터) |
| `strategy_b_select_hold_return_excellent_1280.png` | 보유 유지 + 수익률 순 + 우수 필터 조합 |
| `strategy_b_select_980.png` | 데스크톱 최소 폭 980px에서 1라인 유지 |
| `report_card_excellent.png` | 종목 리포트 현재 판단 카드 "B Select Core V1 우수.관찰" (AJ네트웍스: 2026Q2 영업이익 215억, 전년 180억) |

---

**참고 — MAJOR 상세 (원천 분류 결함)**

- **결함**: `FilingRegistry`가 "해외증권거래소등에신고한사업보고서등의국내신고"를 `11011`(사업보고서), `bsns_year` = 접수 연도로 매핑합니다. 원인은 두 가지입니다. `infer_report_code`가 보고서명에 "사업보고서"라는 글자만 있으면 11011로 분류하고, `infer_business_year`는 보고서명에 기간 표기가 없으면 접수 연도를 회계연도로 씁니다.
  - 로컬 캐시 기준 92행, 7종목(`003600`, `005490`, `015760`, `017670`, `030200`, `034220`, `034730`)입니다.
  - 이 공시에는 XBRL 재무값이 없어서 재무 수치 자체는 오염되지 않습니다. 다만 "최신 공개 분기"를 고를 때 존재할 수 없는 분기가 끼어듭니다.
- **이번 작업의 처리**: UI helper 안에서만 좁게 보정했습니다. 원천 분류기와 지난 연구 산출물은 범위 밖이라 수정하거나 재실행하지 않았습니다.
- **지난 백테스트 영향**: V03/FIX01/V04에서 POSCO홀딩스 2026-06-30 신호 1건이 이 문제로 UNAVAILABLE 처리됐습니다(P1·P2-2·P3-2). 전체 결론(보류)에는 영향이 없을 규모입니다.
- **판단이 필요한 것**: 원천 분류기(`infer_report_code` / `infer_business_year`)를 고칠지는 별도 지시가 필요합니다.
