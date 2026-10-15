# FAST Alignment 500B — CJ CGV execution contract closure V03

**CRITICAL 0 · MAJOR 0 · MINOR 1**

**판정: PASS.** CJ CGV의 정확한 다음 KRX 거래일 체결가격을 확인했고, 공통 체결 경로를 최소 수정했어. 영향은 CJ CGV 한 건으로 제한됐고, 테스트와 저장 전략 보고서 parity가 모두 통과했어. 공식 공개 정본·digest·운영 activation은 별도 사용자 승인 전까지 재생성하거나 게시하지 않았어.

## CJ CGV 체결 감사

- `079160_01`의 Exit 신호일은 2016-09-30이고 정확한 다음 KRX 정상 거래 세션은 2016-10-04야. 그날 KRX raw 시가는 83,600원, 거래량은 189,952주, 거래대금은 15,825,955,600원이야. Naver-native 조정 시가는 52,982원이고 조정 저가 52,412원과 고가 53,616원 안에 있어.
- 2016-10-04 조정 OHLC 봉은 종가 53,617원이 고가보다 1원 높아 분석용 봉에서 제외해. 검증된 정확한 시가만 execution-only로 쓰고 신호 계산에는 섞지 않아. 비율 비교는 보조 확인일 뿐 체결가를 계산하지 않았어.
- 저장 체결일 2016-10-05를 2016-10-04로 교정했어. 웹 gross 수익률은 42.5651%에서 41.2138%로 -1.3513%p, P1 비용 반영 net 수익률은 42.2376%에서 40.8894%로 -1.3482%p 변해. 매도 순수령액은 7,105,856.92원에서 7,038,503.46원으로 67,353.46원 감소해.
- corporate-action 저장소는 상태/전이 메타데이터만 제공해. 2016년 PIT 식별·상장주식수 연속성은 확인했지만, 이 저장소만으로 모든 과거 기업행위가 없었다고 단정하지 않았어. 이 provenance 한계가 유일한 MINOR 항목이야.

## 거래 423건 및 포트폴리오 영향

- V02 감사의 422 PASS / 1 CHECK_REQUIRED 중 CJ CGV 한 건을 다음 KRX 세션으로 바로잡았어. 거래 diff는 **397개 기존 실현거래 불변 + 25개 OPEN_AT_CUTOFF 불변 + CJ 1건 교정**이야. 진입 세션 오류는 0건, 청산 세션 오류는 CJ 1건뿐이었어. 저장 원장 기준 교정 후 감사 상태는 423 PASS야.
- 2016-10-04 NAV 반사실은 191,208,718.64원, T+1 정산 반영 후 10-05 NAV는 191,061,865.64원이야. 10-05 체결 매수는 없고, 이후 최소 매수 현금 여유 134,826.88원이 수령액 감소분보다 커서 이후 체결/현금 부족 상태 변화는 없어.
- P1 NAV coverage 93.2733% → 93.3054%, MDD -32.5790% → -32.5885%, 총수익률 107.6516% → 107.6179%, CAGR 5.9416% → 5.9402%로 제한적으로 변해. 저장된 185쌍 최신 5기간 판정은 모든 기간 A-D PASS, E OBSERVED이며 상태 변화는 없어. worker 오류는 저장된 공식 산출물에서 0건이야. 이번에는 공식 백테스트나 5기간 재생을 실행하지 않았어.
- `trade_parity_diff.csv`는 저장된 거래 감사와 정확한 체결 계약을 대조해 만든 기대 diff야. 전체 public canonical 데이터를 새로 생성하지 않았어.

## 웹 UI 및 테스트

- `web/js/strategy.js`에서 FAST와 B Select 모두 현재 상태 마켓 필터, 거래 이력 마켓 필터와 정렬 선택을 사용할 수 있게 했어. 펀더멘탈 필터는 B Select 전용으로 남겼고 Julia는 바꾸지 않았어.
- 최종 수정 소스 계약/Phase4E/회귀 표적 테스트 **45 passed**, UI 표적 테스트 **1 passed**, 전체 `tests/test_web_strategy.py` **30 passed (580.67초)**야. 첫 전체 실행에서 005930에 거래 이력이 있다고 가정한 오래된 테스트 표본만 실패해서 현재 저장 리포트에서 실현·미종료 이력이 모두 있는 종목을 동적으로 고르도록 수정했고, 전체 재실행이 통과했어.
- monitor 전체 projection과 3개 전략 거래 이력 identity/parity 테스트도 통과했어. 최신 저장 action/reason/bucket projection은 Stock Report와 exporter 비교에서 일치해.

## 보호 및 게시 범위

- 보호 대상 웹 데이터 151개 파일 중 불일치 0개, B Select status SHA도 V02 기준과 일치해. V02 증거 6개, P1 execution contract, 5기간 공식 보고서, V2 전략 문서 및 lifecycle 문서 해시도 그대로야.
- 공개 주식 리포트·웹 정본·Julia 리포트를 재생성하지 않았어. digest 변경·activation·게시도 하지 않았어. 해당 작업은 별도 승인 대상이야.
- 출발 시 `HEAD == origin/main == b964eab2327506669f5618895f23a02972b79289`였고 `git diff --check`는 PASS야. 관련 코드·테스트·감사 산출물만 선별해 commit/push할 수 있어.

## 변경 source/test 파일 SHA-256

- `src/trend_scanner/validation/pattern_a_fast_core_v02_reentry.py` — `c16ea8480685546d354a41f4a7604b5bb272154acd7826fdad0c3f8748b29a6d`
- `src/trend_scanner/reporting/a_fast_core_report.py` — `4806525fe1cc55d1fc4a3863e90475201b05ebd49d3b0adb9fbd44635e0d5331`
- `src/trend_scanner/reporting/stock_report.py` — `70c0329964c07b0d6fd2e5708a0049fc011b83e23502d97036a0da991173f94a`
- `src/trend_scanner/reporting/models.py` — `6cd8edc27d69eaebcd3457748d888daef365f182b8836ac489f5e9abf671c0f5`
- `web/js/strategy.js` — `7f7a8d71756dc15007d94334dfd2a2de7132aed3edf75246f93a4af0595ce4fd`
- `tests/test_pattern_a_fast_core_v02_reentry.py` — `29596021425bbe060f7f47a555b7faff15862656b845d2561a7bd02aaa158883`
- `tests/test_a_fast_alignment_entry_contract_v02.py` — `6f5cd474ac6423b6b129f0d2b235a4c961b5c6438de5cb29a10ca8559700d25e`
- `tests/test_web_strategy.py` — `07f775f1461861981b72f8eb11382d6d34b1d50a38bc30669431337d4d5837e7`

## 산출물

- `validation_summary.json` — 최종 PASS 및 검사 상태
- `cj_execution_source_audit.json` — 날짜·원천·OHLC 유효성·provenance 감사
- `execution_impact.csv` — CJ 체결 비용 및 P1 반사실 영향
- `trade_parity_diff.csv` — 423건의 거래별 변경 대조
- `source_manifest.json` — 코드·원천·보호 파일 hash manifest
