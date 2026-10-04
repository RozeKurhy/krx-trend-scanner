# 웹 영역 안내

이 문서는 `web/` 영역의 전체 구조와 데이터 흐름을 안내한다. 웹 화면의 메뉴
사용법이나 UI 디자인을 설명하는 문서가 아니다.

## 웹 계층의 역할

웹 계층은 원천 데이터를 프로젝트의 권위 기준으로 다시 계산하거나 정의하지
않는다. 대부분의 변환 스크립트는 이미 생성·검증된 원천 데이터와 분석 결과를
웹에서 읽기 쉬운 정적 JSON으로 변환해 전달한다. 다만 웹 제공에 필요한 집계나
기간 수익률을 변환 과정에서 계산하는 예외가 있다.

`web/data/`의 JSON은 웹 표시를 위한 결과물이다. 원천 데이터, 분석 결과,
계산 규칙과 구분하며, 다른 분석이 이 파일을 새로운 권위 기준으로 사용하지
않도록 한다.

## 전체 구조

웹 데이터는 다음 흐름으로 화면에 도달한다.

```text
원천 데이터·분석 결과·종목 리포트
  → 웹용 변환 스크립트
  → web/data/ 정적 JSON
  → web/js/ 페이지별 JavaScript
  → web/*.html 화면
  → GitHub Pages 배포
```

주요 위치는 다음과 같다.

| 위치 | 역할 |
|---|---|
| `artifacts/`, `data/` | 원천 데이터와 프로젝트의 분석·검증 결과 |
| [`scripts/export_*_web.py`](../../scripts/) | 각 결과를 웹 표시용 JSON으로 변환 |
| [`web/data/`](../../web/data/) | 배포에 포함되는 정적 JSON |
| [`web/js/`](../../web/js/) | JSON을 읽고 화면을 구성하는 페이지별 JavaScript |
| [`web/`](../../web/)의 HTML | 사용자가 보는 정적 화면 |

## 주요 데이터 흐름

아래 표는 현재 코드에서 확인되는 큰 흐름만 요약한다. JSON의 세부 필드와
검증 규칙은 각 변환 스크립트와 기존 계약 문서에서 관리한다.

| 화면·데이터 | 주요 원천 또는 선행 결과 | 웹용 변환 스크립트 | 생성되는 JSON | 읽는 JavaScript | 연결 화면 |
|---|---|---|---|---|---|
| 데이터 현황 | Pattern A 스캐너 요약, 시장 권위 목록, PIT 종목 메타데이터, Fundamentals·종목 리포트 산출물 | [`export_web_data.py`](../../scripts/export_web_data.py) | [`health.json`](../../web/data/health.json) | [`app.js`](../../web/js/app.js) | [`index.html`](../../web/index.html) |
| 공포 지수 | 공포 지수의 승인된 일별 상태 CSV와 요약·산식 산출물 | [`export_fear_index_web.py`](../../scripts/export_fear_index_web.py) | [`fear-index.json`](../../web/data/fear-index.json) | [`app.js`](../../web/js/app.js), [`fear.js`](../../web/js/fear.js) | [`index.html`](../../web/index.html), [`fear.html`](../../web/fear.html) |
| ETF 랭킹 | 공식 ETF 36개 메타데이터와 Repository V2 | [`export_etf_ranking_web.py`](../../scripts/export_etf_ranking_web.py) | [`etf-ranking.json`](../../web/data/etf-ranking.json) | [`etf.js`](../../web/js/etf.js) | [`etf.html`](../../web/etf.html) |
| 마켓 RS | 공개 종목 리포트의 `stock-index.json`과 종목별 웹 리포트 | [`export_market_ranking_web.py`](../../scripts/export_market_ranking_web.py) | [`market-ranking.json`](../../web/data/market-ranking.json) | [`market.js`](../../web/js/market.js) | [`market.html`](../../web/market.html) |
| 섹터 RS·섹터 랭킹 | Sector RS 권위 Parquet·메타데이터, 기준일별 KRX Basic Info, 종목 리포트 파일 집합 | [`export_sector_rs_ranking_web.py`](../../scripts/export_sector_rs_ranking_web.py) | [`sector-rs-ranking.json`](../../web/data/sector-rs-ranking.json) | [`sector.js`](../../web/js/sector.js), [`sector-ranking.js`](../../web/js/sector-ranking.js) | [`sector.html`](../../web/sector.html), [`sector-ranking.html`](../../web/sector-ranking.html) |
| 외인 순매수 | 외인 수급 일별 원천과 보통주 권위 집합·섹터 구성. 1·5·10·20·60일 누적 순매수와 같은 기간 주가수익률을 계산하며, `stock-index.json`은 `report_available` 확인에만 사용 | [`export_foreign_net_buy_ranking_web.py`](../../scripts/export_foreign_net_buy_ranking_web.py) | [`foreign-net-buy-ranking.json`](../../web/data/foreign-net-buy-ranking.json) | [`foreign.js`](../../web/js/foreign.js) | [`foreign.html`](../../web/foreign.html) |
| 종목 리포트 | 같은 exact-date COMMON v0.7 + Official ETF36 v0.6 JSON, PIT 종목 메타데이터, 기준일 종가 | [`export_stock_report_web.py`](../../scripts/export_stock_report_web.py) | `stock-index.json`, `stocks/*.json` | [`report.js`](../../web/js/report.js) | [`report.html`](../../web/report.html) |
| 전략 운용 | 공개 COMMON·ETF36 종목 리포트와 B Select exact-date current status | [`build_b_select_core_v1_status.py`](../../scripts/build_b_select_core_v1_status.py), [`export_strategy_monitor_web.py`](../../scripts/export_strategy_monitor_web.py) | [`strategy-monitor.json`](../../web/data/strategy-monitor.json) v2 | [`strategy.js`](../../web/js/strategy.js) | [`strategy.html`](../../web/strategy.html) |

### 종목 리포트와 후속 데이터

종목 리포트 웹 JSON은 여러 화면의 공개 범위를 결정하는 선행 결과다.

- `export_stock_report_web.py`가 같은 exact-date COMMON v0.7 원천과 Official ETF36
  v0.6 원천을 각 계약대로 검증한 뒤 `stock-index.json`과 종목별 `stocks/*.json`으로
  투영한다. ETF36은 Julia V1 authority를 보존하고 Pattern B를 적용하지 않는다.
- 마켓 RS는 공개 종목 리포트 집합을 대상으로 랭킹 JSON을 만든다. 외인 순매수는
  보통주 권위 집합을 대상으로 1·5·10·20·60일 수급 합계와 기간 주가수익률을
  웹 제공용으로 계산한다. 이때 `stock-index.json`은 종목 집합 권위가 아니라
  `report_available` 표시 여부 확인에만 사용한다.
- 섹터 RS는 Sector RS 권위 값을 그대로 투영하고, 종목 리포트 파일 집합은
  `report_available` 표시 여부에 사용한다. `sector.html`은 `items[]`의 업종 내 종목
  순위를 표시하고, `sector-ranking.html`은 같은 JSON의 `sectors[]`에서 기존 계산
  결과인 `sector_return_*`를 읽어 업종 사이 표시 순서를 정한다. 두 화면은 데이터와
  비교 단위가 다르며, 브라우저는 수익률을 다시 계산하지 않는다. 섹터 순위는
  표시용 교차 업종 정렬이고 새 전략이나 새 분석 권위가 아니다. 상승 종목 수는
  설명용 집계이며 순위 기준에 포함하지 않는다.
- 마켓 RS는 공개된 모든 파일의 일치 여부를 확인한 뒤 기존 COMMON 리포트 집합만
  투영한다. Strategy Monitor v2는 A FAST Core V2와 B Select Core V1을 공개 COMMON
  범위로, Julia V1을 Official ETF 36으로 별도 투영한다. 기본 선택은 A FAST Core V2다.
- B Select current status는 고정된 Pattern B 월별 state·Pattern A stage lineage와
  같은 실행의 현재 COMMON 리포트 상태를 exact PIT identity로 replay해 만든다. 일일 상태·가격·
  data health 표시는 유지하고, B Select ENTRY/EXIT는 완결된 월의 마지막 exact KRX 거래일
  observation에서만 생성한다. 신호 다음 exact KRX session open만 채우며 reference 뒤 fill은
  pending으로 남긴다. Web JavaScript는 전략을 계산하지 않고 전략 선택·검색·필터·정렬과 표시만
  수행한다.

## 웹 데이터 생성 원칙

- 웹용 변환 스크립트는 원천 데이터와 이미 계산된 분석 결과를 읽고 표시용 구조로
  변환한다.
- 외인 순매수 변환 스크립트처럼 웹 제공에 필요한 기간별 수급 합계와 주가수익률을
  계산하는 예외가 있다. 이 계산 결과도 웹 표시용 산출물이며 프로젝트의 새로운
  권위 기준이 아니다.
- 웹 계층에서 RS, 공포 지수, 전략 판단, 재무 수치 같은 기존 값을 임의로
  다시 계산하지 않는다. B Select current status는 Phase4C의 별도 Python evaluator가
  한 번 생성해 Phase4D에 전달하고 날짜별 artifact와 Monitor JSON에 반영한다.
  브라우저 JavaScript는 이를 다시 계산하지 않고 projection으로 표시한다.
- 원천·분석 결과의 기준일과 공개 범위를 JSON에 필요한 수준으로 전달하되,
  웹 JSON을 새로운 계산 권위로 승격하지 않는다.
- 현재 구현에서 다른 웹 투영 결과를 입력으로 사용하는 경우는 숨기지 않는다.
  마켓 RS의 공개 리포트 집합과 전략 운용 모니터가 이에 해당한다. 외인 순매수의
  `stock-index.json` 사용은 종목 집합 권위가 아니라 `report_available` 확인용이다.
- 변환 스크립트가 쓰는 파일은 `web/data/` 아래의 정적 결과물이며, 화면의
  JavaScript는 해당 파일을 읽기만 한다.

## 배포 흐름

`.github/workflows/pages.yml`은 `main`에 반영된 변경 또는 수동 실행을 계기로
저장소를 확인하고 `web/` 폴더 전체를 Pages 산출물로 올린다. 이후 GitHub
Pages가 그 정적 산출물을 배포한다.

따라서 웹 화면에 반영되는 경로는 다음과 같다.

```text
main 반영
  → Pages workflow 실행
  → web/ 폴더 업로드
  → GitHub Pages 배포
```

## 세부 문서와의 관계

[`sector_rs_web_payload_v01.md`](sector_rs_web_payload_v01.md)는 웹 전체 구조를
설명하는 문서가 아니다. Sector RS 권위 값, 기준일별 이름 결합, 전달 형식의 범위와
직렬화 조건을 다루는 세부 계약 문서다.

전체 웹 흐름은 이 README에서 확인하고, Sector RS 전달 형식의 세부 의미와
검증 경계는 해당 계약 문서를 따른다.
