# Julia Strategy Authority & Index

본 디렉터리는 **`A FAST Core V2` (PATTERN_A_FAST_FINAL_STRATEGY_V02)**를 기반으로 한 탐색적 연구 변형 모델인 **`Julia Strategy`** 연구 산출물과 명세서를 관리합니다.

---

## 🌟 Julia Strategy 트랙 개요

- **기본 전략 (Base Strategy)**: `PATTERN_A_FAST_FINAL_STRATEGY_V02`
- **핵심 연구 질문**: *"Pre-PROGRESSED -15% Loss Guard를 제거했을 때, 대형 손실 방어 효과와 상승 기회 회수 간의 상충 관계는 어떠한가?"*
- **연구 상태 (Classification)**: **`EXPLORATORY_CANDIDATE`**
- **실증 방식 (Validation Type)**: **`SAME_SAMPLE_RETROSPECTIVE`**
- **공식 기본 전략**: **`A FAST Core V2` 유지 (Julia는 프로덕션 미승인 상태)**

---

## 📂 문서 인덱스

1. **[Julia Strategy V00 Report (2022+ Controlled Backtest)](v00.md)**
   - 2022-01-01 ~ 2026-08-14 기간 동안 Baseline V2와 Julia V00의 100% 동일 조건 제어 비교 백테스트 결과
   - Full Strategy Path, Common-Entry Paired Counterfactual, Loss Guard Recovery & Deep Loss 정량 분석
2. **아티팩트 경로**: `artifacts/strategies/julia/v00/`
   - `contract.json`: 불변 계약 메타데이터
   - `baseline_a_fast_core_v2_2022_trades.csv`: Baseline 2022+ 거래 목록 (696건)
   - `julia_v00_2022_trades.csv`: Julia V00 2022+ 거래 목록 (556건)
   - `common_entry_pairs.csv`: 공통 진입 556개 페어 상세 비교
   - `loss_guard_counterfactual.csv`: Baseline 손절 292건의 사후 추적 상세 테이블
   - `strategy_comparison_summary.json` & `strategy_comparison_metrics.csv`
   - `worst_losses.csv` & `big_winners.csv`
