# FAST Core V2 Alignment + 500B — P2-1 실행 계획

- 작업 ID: FAST_CORE_V2_ALIGNMENT_500B_P2_1_OFFICIAL_REALISTIC_184_V01
- 기준 커밋: ff3d200f2192745c83256d3435e4d0b59a6891cc; 실제 실행 전 HEAD == origin/main과 추적 작업트리 상태를 재확인한다.
- 대상은 P2-1의 frozen PATTERN_A_FAST_FINAL_STRATEGY_V02 CONTROL과 동일 frozen V2에 진입 필터 두 조건만 추가한 ALIGNMENT_MCAP_500B다.
- 기간: 달력 범위 2021-01-01~2025-05-31, 정확 KRX 평가 세션 2021-01-04~2025-05-30. 2025-06-02는 cutoff 이전 청산 신호의 다음 시가 체결 확인만 지원한다. MA60 선행 완성 월은 2016-01~2020-12다.
- 공통 유니버스는 rolling PIT의 신호일 활성 COMMON exact identity와 승인된 184 (ticker, standard ISU_CD) 쌍을 적용해 P2-1 자체로 구축한다. 예상 canonical hash (sorted_exact_pair_json_v01)는 5d3bd9a1e27e7e558235f0fba211263cdc90eb0b477978c8338eb019b1a6ec2e다.
- 후보 신규 진입 조건은 신호일 조정종가 > 이전 완료 월봉 MA20 > MA60 및 같은 날/시장/exact PIT identity의 raw 시총 >= 500,000,000,000원이다. 조건은 frozen V2 상태가 소비되기 전에 적용하며 CONTROL에는 후보 필터를 적용하지 않는다.
- 공통 포트폴리오: 초기 2억원, 매수당 수수료 포함 500만원 예산, 정수주, 부분 체결·인위적 포지션 수 제한 없음, 양방향 슬리피지 0.1%, 양방향 수수료 0.015%, 거래세 공식 제외, 매도대금 T+1 가용, 동일 시가 매도대금 재사용 금지. 지원일 손익/NAV는 cutoff 성과에서 분리한다.
- 공식 A~E 기준은 docs/validation/official_strategy_adoption_criteria.md를 그대로 적용한다. 현금 부족률은 진단이며 게이트가 아니다.
- 10 workers로 전체 신호 평가 후 그룹별 단일 결정적 chronological replay를 한 번씩 수행한다. 샘플 구조 검증을 먼저 수행하며 표본 NAV coverage <90%만으로 전수 실행을 차단하지 않는다.
- P1/P2-2/P3 재실행, 전략 규칙 변경·튜닝, 운영·웹 수정, 외부 API 호출, 사후 종목 제외/정산 추정은 범위 밖이다.
- 결과물은 이 폴더와 /Users/june/Documents/projects/r.md에 기록한다. 연구 산출물만 커밋/푸시하고 완료 시 HEAD == origin/main과 tracked clean을 확인한다.

## 실행 순서

1. 소스/기준 문서 및 비교 산출물의 내용과 SHA-256, Git 기준, rolling PIT/calendar, exact 184 pair, adjusted/raw date-market 범위를 독립 검사한다.
2. plan.md, execution_contract.json, preflight.json, source_manifest.json을 표본 실행 전에 봉인한다.
3. 약 30 ticker 표본으로 P2-1 전용 frozen signal evaluator와 실제 포트폴리오 replay를 실행하고 identity, future/cutoff, 비용, 현금, 필터 parity, NAV 원인을 확인한다.
4. 구조 검증 통과 및 실행시간 예상이 공통 원칙 안일 때만 전체 신호 평가를 10 workers로 한 번 수행한다.
5. CONTROL/후보 portfolio replay를 각각 단 한 번 실행하고 원장·비용·NAV·P2-1 A~E를 독립 재검산한다.
6. report.md, artifact_hashes.json, r.md를 기록하고 필요한 연구 산출물만 커밋/푸시한다.
