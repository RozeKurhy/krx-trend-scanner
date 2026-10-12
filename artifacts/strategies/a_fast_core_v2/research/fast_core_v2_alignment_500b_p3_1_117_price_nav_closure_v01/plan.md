# FAST Core V2 P3-1 117종목 가격·NAV 종결 감사 V01

- 작업 ID: `FAST_CORE_V2_ALIGNMENT_500B_P3_1_117_PRICE_NAV_CLOSURE_V01`
- 기준 HEAD: `bef07ad77f56222b468c3efb65f04008735cec5c` (실행 전 `origin/main`과 일치 확인)
- 범위: 기존 P3-1의 117개 가격 입력 미해결을 정확한 ticker/ISU identity 기준으로만 복구하고, CONTROL 및 Alignment+500B P3-1을 재판정한다.
- 기존 공식 P3-1 결과 폴더는 불변 보존한다. P3-2는 원인·bounded-load 방법 참고용이며 그 신호/거래 원장을 복사하지 않는다.

## 고정 조건

- 평가 기간은 2022-01-03~2025-05-30의 KRX 834거래일이다. 2025-06-02는 cutoff 전 청산 신호의 다음 거래일 체결에만 쓴다.
- CONTROL은 원본 FAST Core V2다. 후보는 신호일 Repository V2 조정 종가 > 직전 완료 월봉 MA20 > MA60(신호월 제외, 60개월) 및 같은 날 정확한 PIT identity의 KRX raw 시가총액 >= 5,000억 원 조건만 추가한다.
- 양쪽 모두 현행 승인된 182개 영구 제외 쌍을 전략 계산 전에 적용한다.
- 현금 2억 원, 종목별 수수료 포함 매수예산 500만 원, 정수 주식, 매수·매도 다음 거래일 시가, 양방향 0.1% 슬리피지와 0.015% 수수료, 거래세 0%, 매도대금 T+1 가용, 현금 부족 skip 후 신호 재생성 금지다.
- P1/P2-1/P2-2/P3-2 실행, 전략 규칙·운영·웹 변경, 가격 보간, 기존 결과 덮어쓰기, 5기간 채택 및 승격을 하지 않는다.

## 실행 방식

1. 공식 기준·공통 규칙·전략 README와 기존 P3-1/P3-2 원장의 SHA-256을 확인하고, 기존 P3-1 산출물 및 2,343개 정상 종목 입력의 해시를 검증한다.
2. 기존 P3-1 무결성 감사의 117개 정확한 ticker/ISU 쌍이 P3-2 bounded-load 123개 안에 전부 들어가는지 재확인한다.
3. 종목별 adjusted 파일의 첫 유효 관측일에서 2025-06-02까지 Repository V2를 읽어 전체 raw-only 선행 세션을 배제한다. PIT 내부 불일치가 0인지, 2022~2025 평가 구간 및 신호별 60개월 월봉 예열이 완전한지 개별 감사한다.
4. 동결된 P3-1 evaluator를 10 workers로 이 117개 ticker에만 적용한다. 기존 P3-1의 2,343개 정상 신호/거래 입력은 해시 검증 후 그대로 재사용한다.
5. 신규 거래 신호가 하나라도 있으면 신호 원장을 먼저 병합·중복 검증한 후 CONTROL과 후보의 P3-1 포트폴리오를 각각 처음부터 순차 재생한다. 신규 신호가 없을 때만 기존 결과를 재사용한다.
6. 새 포지션 기준 코엔텍 기업행위, 후보 003690의 네 NAV 결측일, A~E, 원장·비용·현금 보존·provenance를 재검증한다. 성과 숫자로 규칙이나 판정기준을 바꾸지 않는다.

## 완료 조건

- 9개 필수 산출물(`report.md`, `price_input_117_audit.csv`, `replay_decision.json`, `metrics_comparison.csv`, `gate_results.json`, `integrity_validation.json`, `corporate_action_audit.md`, `source_manifest.json`, `artifact_hashes.json`)을 기록한다.
- 필요한 경우 두 그룹의 신규 병합 신호/거래, 이벤트, 현금, 일별 NAV, skip/valuation 및 worker 원장을 추가한다.
- 독립 원인 기준 CRITICAL/MAJOR/MINOR 유형 개수, 결과와 잔여 미해결 사유를 `/Users/june/Documents/projects/r.md`에 기록한다.
- 새 closure 산출물만 commit/push하고, push 후 `HEAD == origin/main`, tracked working tree clean을 확인한다. 무관한 미추적 연구 파일은 stage하지 않는다.
