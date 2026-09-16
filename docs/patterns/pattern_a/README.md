# Pattern A

- **패턴**: Pattern A
- **목적**: 장기 베이스와 대세 상승 구조 탐지
- **현재 운영 상태**: `FROZEN` / `KEEP_CURRENT_PRODUCTION`
- **현재 점수 버전**: Score v0.2 (`KEEP`)
- **현재 단계 계약**: Stage v0.1 (`KEEP`)
  - 단계 값: `WEAK`, `BASE`, `TRANSITION`, `EARLY_TREND`, `PROGRESSED`
- **Pattern A 단계 연구**: `CLOSED`
- **동결 원칙**: `FROZEN` — Score/Stage 산식과 임계값은 이 안내 문서
  정리 작업을 포함해 변경하거나 재해석하지 않는다.
- **다른 패턴과 관계**: [Pattern A FAST](../pattern_a_fast/README.md)는
  Pattern A보다 빠른 상승 전환을 탐지하는 별도 보조 패턴이다. 관련성은
  있지만 검증 이력과 기준 문서는 독립적으로 관리한다.

## 현재 기준 문서

이 문서는 안내와 탐색만 제공한다. 산식과 결론은 아래 기준 문서에서 확인한다.

- **Pattern A 공식 규격**: [spec/production_authority.md](spec/production_authority.md)
  — Score/Stage 정의와 누적 검증 근거
- **최종 운영 확정 기록**: [validation/final_production_closure.md](validation/final_production_closure.md)

## 연구·검증·역사 기록 위치

- `spec/` — 현재 Pattern A 공식 규격
- `research/` — Pattern A 자체의 연구 기록
- `validation/` — evaluator, 단계 분류, 투자 적합성, 음성 대조군,
  유니버스·데이터 품질, 차트 검토 등의 검증 기록
- `archive/` — 현재 기준으로 대체되었지만 보존하는 역사 문서
