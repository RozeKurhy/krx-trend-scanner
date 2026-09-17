# Architecture 문서 전수 분류 검토 V01

작업일: 2026-09-17 (Asia/Seoul)  
Repository: `RozeKurhy/krx-trend-scanner`  
Branch: `main`  
실제 시작 HEAD: `ca6ede9cf43cead667759d25682bc771096572ed`

## 1. 조사 기준

이번 문서는 `docs/architecture/` 아래에 작업 시작 시 존재한 모든 Markdown을
재귀적으로 조사한 분류표다. `artifacts/`, `errata/`, `validation/` 하위 문서를
포함했으며, 이 통제 문서 자체는 원본 조사 대상 수에서 제외했다.

- 원본 조사 대상: **22개 Markdown**
- `docs/README.md`: 확인함
- `docs/architecture/README.md`: 확인함
- 기존 `docs/architecture/**/archive/`: 확인되지 않음
- 판단 기준: 문서 본문 전체, 현재 authority/계약, 현재 구현·문서 참조 관계
- 이번 단계에서 기존 문서 이동·삭제·본문 수정·링크 수정은 수행하지 않음

## 2. 분류 요약

| 분류 | 개수 |
|---|---:|
| KEEP | 16 |
| ARCHIVE | 6 |
| DELETE_CANDIDATE | 0 |
| 합계 | **22** |

`KEEP + ARCHIVE + DELETE_CANDIDATE = 16 + 6 + 0 = 22`로 원본 조사 대상 수와
일치한다.

## 3. 문서별 분류표

| 파일 경로 | 현재/역사 역할 | 분류 | 판단 근거 | 후속 처리 제안 |
|---|---|---|---|---|
| `docs/architecture/README.md` | Architecture navigation | KEEP | 공용 infrastructure 문서와 validation 하위 영역의 현재 진입점이다. | 유지. 현재 핵심 문서 링크 보강은 별도 정리 단계에서 검토한다. |
| `docs/architecture/adjusted_price_store_v01.md` | Adjusted OHLC store 계약 | KEEP | adjusted price authority, store 경로·무결성·refresh 경계를 정의하고 현재 architect review 대기 상태를 명시한다. | 유지. 승인 전 `CLOSED`로 바꾸지 않는다. |
| `docs/architecture/artifacts/artifacts_information_architecture_audit_v01.md` | Artifacts IA 감사·이동 설계 | KEEP | 현재 artifact authority, runtime path dependency, archive 후보, 다음 이동 단계의 위험과 순서를 확정한 현재 통제 기록이다. | 유지. 실제 이동·삭제는 별도 리뷰 PASS 후 수행한다. |
| `docs/architecture/corporate_action_dirty_refresh_v01.md` | Corporate-action dirty/refresh 계약 | KEEP | `LIST_SHRS`·`PARVAL` 신호, fail-closed refresh 흐름, 현재 AdjustedPriceStore 연계를 정의한 다음 단계 계약이다. | 유지. architect review 전 production consumer 전환은 하지 않는다. |
| `docs/architecture/data_layer.md` | 공용 데이터 레이어 계약 | KEEP | PyKRX 일봉 정규화, repository/provider/cache 역할과 현재 공용 데이터 구조를 설명한다. | 유지. architecture 공용 기준으로 사용한다. |
| `docs/architecture/errata/krx_identifier_contract_errata_v01.md` | KRX identifier 보정 기록 | KEEP | 기존 closed 계약을 다시 쓰지 않고 영숫자 단축코드 사실을 보정 overlay로 명시하는 현재 errata다. | 유지. 원본 history를 재작성하지 않는다. |
| `docs/architecture/historical_snapshot.md` | Historical Snapshot/PIT validation 계약 | KEEP | snapshot cutoff, completed/live 기간, lookahead 방지와 검증 저장 형식을 정의하는 현재 validation infrastructure다. | 유지. PIT 기준 문서로 사용한다. |
| `docs/architecture/instrument_metadata_authority.md` | Instrument metadata authority | KEEP | `InstrumentMetadataResolver`가 사용하는 KRX formal source, PIT 선택, provenance, fail-closed trust rule을 현재 기준으로 고정한다. | 유지. legacy row와 current verified row를 혼동하지 않는다. |
| `docs/architecture/krx_dual_provider_contract_v01.md` | KRX/PyKRX dual provider 역할 계약 | KEEP | raw·adjusted source 분리, corporate-action dirty trigger, quota와 production 연결 전 경계를 정의한다. `NOT CONNECTED IN FIX01`은 현재 migration 상태이지 폐기 선언이 아니다. | 유지. provider 연결은 별도 승인 단계에서 진행한다. |
| `docs/architecture/krx_historical_backfill_v01.md` | KRX raw historical backfill 계약 | KEEP | whole-market immutable partition, quota/resume, raw schema와 architect review 전 상태를 정의하는 현재 후속 phase 계약이다. | 유지. backfill 실행·대량 생성은 이 분류 작업에서 수행하지 않는다. |
| `docs/architecture/krx_index_migration_v01.md` | Market index source migration 계약 | KEEP | KOSPI/KOSDAQ index mapping, staging/publish, parity와 migration 미완료 경계를 정의하며 production data architecture dependency graph에 남아 있다. | 유지. consumer 전환 전 parity gate를 별도로 통과한다. |
| `docs/architecture/krx_index_series_mapping_v01.md` | Native sector index validation 계약 | ARCHIVE | native 46개 sector index의 identity 검증을 기록한 validation-only 문서다. 이후 `sector_rs_krx_migration_v01.md`에서 KRX Open API 기반 production Sector RS source 전환이 완료되어 현재 production authority가 아니다. | `docs/architecture/archive/krx_index_series_mapping_v01.md`로 이동 제안. 과거 mapping 검증 증적으로 보존한다. |
| `docs/architecture/krx_open_api_v02_validation.md` | KRX Open API V02 bounded validation 경계 | ARCHIVE | endpoint semantic, PIT snapshot, quota 40회 경계를 검증한 단계 문서다. 이후 Repository V2 production refresh 체계가 구현되어 현재 production authority가 아닌 과거 검증 기록이다. | `docs/architecture/archive/krx_open_api_v02_validation.md`로 이동 제안. bounded validation 결과를 역사 기록으로 보존한다. |
| `docs/architecture/krx_production_data_architecture_v01.md` | Production data authority/저장소 종합 계약 | KEEP | raw·adjusted·master·classification·index·membership·fundamentals authority와 Repository V2/PIT/provenance/health를 종합적으로 고정한다. | 유지. architecture 영역의 핵심 authority boundary로 사용한다. |
| `docs/architecture/market_data_repository_v02.md` | Repository V2 composition 계약 | KEEP | adjusted OHLC와 raw ancillary의 read-only join, ETF contract, session projection과 fail-closed semantics를 현재 target contract로 정의한다. | 유지. consumer migration은 별도 parity 단계에서 한다. |
| `docs/architecture/sector_rs_krx_migration_v01.md` | Sector RS production source/membership 계약 | KEEP | KRX native 46-sector index와 공식 Marketplace exact-date membership의 현재 production acquisition·PIT 규칙을 정의한다. | 유지. approved snapshot exact-date 원칙을 적용한다. |
| `docs/architecture/survivorship_safe_denominator_freeze_v01.md` | Survivorship-safe population/PIT denominator 계약 | KEEP | 모든 향후 E2E consumer가 사용할 canonical population/PIT freeze와 loader/fail-closed 계약을 현재 기준으로 명시한다. | 유지. consumer별 universe 재계산을 허용하지 않는다. |
| `docs/architecture/validation/common_cache_population_v01.md` | Phase 7 common cache population 완료 보고 | ARCHIVE | 2026-08-14 고정 snapshot의 Phase 7 완료·캐시 품질·실측 수치와 다음 Phase 8을 기록한 결과 보고다. 현재 production authority/운영 contract는 이후 production data architecture와 현재 store 계약에서 다룬다. | `docs/architecture/archive/validation/common_cache_population_v01.md`로 이동 제안. 실제 이동 전 참조·현재 사용 여부를 별도 리뷰한다. |
| `docs/architecture/validation/historical_market_cap_backfill_v01.md` | Historical market-cap PIT source correction 계약 | ARCHIVE | Phase 13J-1 이전 frozen active source와 보정 기준을 기록한 단계 문서다. 이후 Phase 13J-1 작업이 실제 수행되어 현재는 역사적 입력·검증 기록이다. | `docs/architecture/archive/validation/historical_market_cap_backfill_v01.md`로 이동 제안. 과거 PIT source 보정 근거를 보존한다. |
| `docs/architecture/validation/krx_open_api_validation_v01.md` | 초기 KRX Open API bounded validation 결과 | ARCHIVE | 2026-08-14의 HTTP 401/Unauthorized 결과와 migration 보류 판단을 보존하는 실패·전환 기록이다. 현재 V02 validation boundary와 후속 production architecture가 현재 기준이다. | `docs/architecture/archive/validation/krx_open_api_validation_v01.md`로 이동 제안. 인증 실패 원인은 역사 증거로 보존한다. |
| `docs/architecture/validation/phase12_sector_source_investigation.md` | Phase 12 sector source 조사 결과 | ARCHIVE | KRX 접근 제한으로 0-row가 된 초기 조사와 HOLD 판정을 기록한다. 현재 sector RS 계약은 공식 Marketplace snapshot과 native index를 사용하는 후속 문서로 대체되었다. | `docs/architecture/archive/validation/phase12_sector_source_investigation.md`로 이동 제안. 원래 제한·실패 근거는 보존한다. |
| `docs/architecture/validation/test_suite_performance_audit_v01.md` | Test infrastructure 성능 감사·refactor 기준 | KEEP | slow/integration 분리, full-universe scan 재호출 방지, stale guard 정정과 남은 performance debt를 현재 test 운영 기준으로 기록한다. | 유지. 일반 test 실행 정책과 후속 성능 작업의 기준으로 사용한다. |

## 4. 현재 권위와 경계

### 현재 핵심 authority

- 공용 데이터 구조: `data_layer.md`
- production authority matrix와 logical store/PIT/provenance: `krx_production_data_architecture_v01.md`
- adjusted OHLC: `adjusted_price_store_v01.md` 및 production architecture의 adjusted authority contract
- instrument metadata: `instrument_metadata_authority.md`와 formal product-master 분류
- raw KRX snapshot/backfill: `krx_historical_backfill_v01.md` 및 production architecture의 raw authority
- composed daily access: `market_data_repository_v02.md`
- sector RS: `sector_rs_krx_migration_v01.md`의 native index와 exact-date membership
- survivorship-safe denominator: `survivorship_safe_denominator_freeze_v01.md`

### Navigation과 경계

`docs/architecture/README.md`는 공용 data layer, historical snapshot, instrument
metadata, validation 디렉터리를 안내하지만, 현재 핵심인 production data,
repository, adjusted store, sector RS, denominator 문서까지 모두 직접 링크하지는
않는다. 이는 navigation 보완 후보로 기록하며 이번 단계에서는 README를 수정하지
않는다.

초기 Open API/sector 조사 문서는 실패 원인과 전환 경로를 보존하는 역사 기록으로
현재 실행 지시와 분리해야 한다. 반대로 `v01`·`migration`·`historical`이라는
이름만으로 archive하지 않았다. 현재 dependency graph, active reference source,
현재 runtime/validation contract를 본문에서 확인한 문서는 KEEP으로 남겼다.

다음 단계에서 특히 주의할 path dependency는 다음과 같다.

- artifacts IA 문서가 기록한 production runtime의 hard-coded artifact path
- adjusted/raw store 및 Repository V2의 source boundary
- sector membership의 exact-date snapshot과 migration 상태
- survivorship freeze loader를 통한 PIT denominator 소비
- test performance 문서의 `slow`/`integration` 실행 경계

## 5. 애매하거나 리뷰가 필요한 문서

- `common_cache_population_v01.md`: Phase 7 완료 보고이면서 cache 운영 원칙도
  포함하므로 ARCHIVE 제안은 현재 runtime 참조가 없다는 전제에서만 확정한다.
- `krx_index_migration_v01.md`: target migration 문서지만 production data
  architecture dependency graph에 남아 있으므로 KEEP으로 분류했다. 실제
  migration 완료 여부는 이 문서 분류와 별도다.
- `krx_open_api_v02_validation.md`, `krx_index_series_mapping_v01.md`,
  `historical_market_cap_backfill_v01.md`: 이전 분류에서는 현재 validation 또는
  active reference로 보았으나, 리뷰에서 후속 production refresh·Sector RS 전환·
  Phase 13J-1 수행 사실이 확인되어 ARCHIVE로 보정했다.
- `test_suite_performance_audit_v01.md`: 실행 결과 기록 성격이 있으나 현재
  default test marker와 남은 debt를 설명하므로 KEEP했다.

이번 단계에서는 위 애매 항목을 추가 조사하거나 분류를 강제로 확정하지 않고,
별도 리뷰에서 확인할 수 있도록 남긴다.

## 6. 셀프 리뷰

- 원본 `docs/architecture/**/*.md` 22개를 재귀 목록과 대조했고 누락 없음.
- 분류 합계 `16 + 6 + 0 = 22` 확인.
- 지정된 3개 문서만 KEEP에서 ARCHIVE로 변경했고 기존 ARCHIVE 3개는 유지함.
- 분류 단계에서는 기존 Markdown 본문·링크·코드·artifact를 수정하지 않음.
- 각 분류는 파일명만이 아니라 본문에 적힌 authority, 상태, runtime/validation
  역할, 역사적 결과를 근거로 작성함.
- current contract와 historical investigation/실패 기록의 경계를 보수적으로
  유지함.
- DELETE_CANDIDATE는 고유 정보 손실 가능성을 피하기 위해 0개로 유지함.
- 분류 단계의 새 파일은 이 통제 문서 1개뿐이며, 실제 archive 이동은 §8에서
  별도로 수행함. 삭제는 수행하지 않음.

## 7. 분류 단계의 작업 범위 외

pytest, backtest, 외부 API 호출, production 코드 수정, artifact 생성·수정,
KEEP 문서 본문 정리는 분류 단계에서 실행하지 않았다. 별도 리뷰 PASS 후
ARCHIVE 이동을 §8에서 완료했으며, 삭제 후보 처리와 KEEP 문서 내용 정리는
아직 시작하지 않았다.

## 8. ARCHIVE 실제 이동 완료

분류 리뷰 PASS 후 ARCHIVE 6개를 실제 이동했다. 원본 분류표의 source path
기록은 분류 당시 기준이므로 그대로 보존한다.

- `docs/architecture/krx_index_series_mapping_v01.md` → `docs/architecture/archive/krx_index_series_mapping_v01.md`
- `docs/architecture/krx_open_api_v02_validation.md` → `docs/architecture/archive/krx_open_api_v02_validation.md`
- `docs/architecture/validation/common_cache_population_v01.md` → `docs/architecture/archive/validation/common_cache_population_v01.md`
- `docs/architecture/validation/historical_market_cap_backfill_v01.md` → `docs/architecture/archive/validation/historical_market_cap_backfill_v01.md`
- `docs/architecture/validation/krx_open_api_validation_v01.md` → `docs/architecture/archive/validation/krx_open_api_validation_v01.md`
- `docs/architecture/validation/phase12_sector_source_investigation.md` → `docs/architecture/archive/validation/phase12_sector_source_investigation.md`

실제 이동 외에 6개 archive 문서 본문은 수정하지 않았다.

`validation/`은 현재 KEEP 영역으로 유지하고, `archive/validation/`은 과거
validation/investigation 기록 영역으로 분리했다. 이에 따라 README에서 두
navigation을 별도 행으로 안내한다. 그 외 코드·artifact·문서 링크는 수정하지
않았다.
