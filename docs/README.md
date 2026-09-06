README.md

# KRX Trend Scanner Documentation Index

이 문서는 `docs/` 전체의 Authority Index다. 각 하위 README가 다시 그 영역의 Authority Index 역할을 한다.

## 최상위 영역

| 영역 | 설명 |
|---|---|
| [architecture/](architecture/README.md) | Pattern에 종속되지 않는 공용 infrastructure 문서 |
| [patterns/](patterns/README.md) | Pattern별 spec / strategy / research / validation / prereg / archive |
| [reporting/](reporting/README.md) | Pattern과 독립된 상위 계층 — Stock Report |
| [strategies/](strategies/README.md) | 여러 Pattern을 조합하거나 Pattern과 독립적인 매매 전략(향후 Julia 등) |

## 현재 Production Pattern

- **Pattern A** — `FROZEN` / `KEEP_CURRENT_PRODUCTION` ([patterns/pattern_a/README.md](patterns/pattern_a/README.md))
- **Pattern A FAST** — Current Strategy: A FAST Core V2, `FINAL_STRATEGY_FROZEN`, `PRODUCTION_DECISION_SUPPORT` ([patterns/pattern_a_fast/README.md](patterns/pattern_a_fast/README.md))

## 현재 Reporting

- **Stock Report** — Version 0.2, Production Integration `CLOSED` ([reporting/stock_report/README.md](reporting/stock_report/README.md))

## 현재 Strategy 상태

- A FAST Core V2는 Pattern A FAST 내부(`patterns/pattern_a_fast/strategy/`)에 존재하는 frozen production strategy다.
- 향후 독립 파생 전략(예: Julia Strategy)은 `strategies/` 아래 배치한다.

## Roadmap

[ROADMAP.md](../ROADMAP.md)

## 문서 작성 규칙 / Naming Convention

- 문서 분류는 1차 영역(architecture/patterns/reporting/strategies) → 2차 Pattern(pattern_a, pattern_a_fast, ...) → 3차 역할(spec/strategy/research/validation/prereg/archive) → 4차 구체적 문서명 순으로 좁힌다.
- 경로 자체가 Pattern/역할 정보를 제공하므로 파일명에서 같은 말을 반복하지 않는다(Pattern 폴더 안에서는 `pattern_a_`, `pattern_a_fast_` 접두사를 쓰지 않는다).
- `prereg/` 폴더 안에서는 파일명 끝에 `_prereg`/`_preregistration`을 다시 붙이지 않는다.
- 문서에 explicit version이 없으면 임의로 버전 번호를 만들지 않는다.
- `archive/`는 단순히 "옛날 문서"가 아니라 현재 authority가 아니고 superseded된 문서만 넣는다. 공식 historical baseline(예: A FAST Core V1)은 archive가 아니라 해당 역할 폴더(`strategy/`)에 유지한다.
- README는 각 영역의 Authority Index다 — 산식/결론을 새로 작성하지 않고 authority 문서로 navigation만 제공한다.

## docs/specs, docs/validation 안내

기존 `docs/specs/`, `docs/validation/`는 이번 재편으로 대부분 위 새 구조로 흡수되었다. `docs/validation/`에 남아 있는 파일은 frozen artifact provenance compatibility stub뿐이며(각 파일에 `LEGACY PATH / COMPATIBILITY ONLY` 및 canonical 경로가 명시되어 있다), authority가 아니다.
