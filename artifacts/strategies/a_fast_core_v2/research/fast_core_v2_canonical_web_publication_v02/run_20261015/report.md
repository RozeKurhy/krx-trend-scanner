| CRITICAL | MAJOR | MINOR |
|---:|---:|---:|
| 0 | 0 | 0 |

# A FAST Alignment 500B 공식 정본 승격·웹 게시 V02

- 결과: A_FAST_ALIGNMENT_500B_CANONICAL_WEB_PUBLICATION_V02_PASS
- 작업 ID: A_FAST_ALIGNMENT_500B_CANONICAL_WEB_PUBLICATION_V02
- 요청일 / 시장일: 2026-10-11 / 2026-10-08
- 승인 V08 digest: e3c6ecc19187eb8951c1c9ef1626a2b54a9cffe1f6d415721b75a0cca8e89b61
- sealed V02 digest: b81d708f8794381e6e9a37c0dad8c9811163f199401af87a057f6bcfb271cbb1; G6_V02_DIGEST_PARITY=FAIL_PRESERVED

## 단계별 결과

| 단계 | 결과 | 확인 내용 |
|---|---|---|
| 시작 상태·백업 | PASS | 시작 main의 HEAD와 origin/main이 d8f6482096dfcda19d693e6e512a7df3acce4a9c(으)로 같았어. 공식 보고서 2,918개, web/data 1,652개, B Select status, Julia ETF 보고서 73개, 운영 config/history 백업과 SHA 검증이 통과했어. |
| 승인 V08 저장물 검증 | PASS | 승인 증거 SHA 6/6 일치. COMMON/JSON/Markdown 각 1,459개, strategy ID/mode/digest/date/scope, 거래 423 (REALIZED 398 / OPEN_AT_CUTOFF 25), gate audit 20,012행을 확인했어. 전략 재생은 하지 않았어. |
| NOOP 회귀 | PASS | 기존 V2 웹이 승인 Alignment 정본을 반영하지 않았으면 NOOP를 금지하고 staging으로 진행해. 정합된 Alignment와 기존 V2 경로의 NOOP는 유지하고 정본 손상은 차단해. |
| 공식 정본 승격 | PASS | artifacts/reporting/stock_reports/20261011/을 V08로 교체했어. 전후 파일 수 2,918, 전체 파일 SHA가 승인본과 일치해. 다른 날짜·ETF 정본은 바꾸지 않았어. |
| Phase4D 표준 dry-run | PASS | source injection 없이 지정 CLI로 실제 staging했어. COMMON 1,459 + ETF 36, 전략 모니터 3행, FAST Alignment 1행, health NORMAL, 6개 필수 payload, network calls 0. |
| 151개 부가 파일·라우트 | PASS | promote() 최종 스냅샷 및 실제 readback에서 stocks/ 밖 보호 파일 151개 SHA 일치, 누락/변경 0. identity route 399개/고유 대상 399개, 끊긴 경로 0. |
| Phase4D live 게시 | PASS | --execute-live가 성공했고 게시 상태는 COMMITTED_AND_READ_BACK. network calls 0. Phase4D의 게시 경계는 web/data 디렉터리 교체와 B Select status 별도 교체라 전역 atomic은 아니며, 기존 rollback/post-readback 경로를 통과했어. |
| 실제 readback·3자 parity | PASS | 1,459개 종목 action/state/position 불일치 0. canonical–compact–monitor 거래 423건, status 398/25, 모니터 필드 불일치 0. compact 내역은 exporter whitelist 때문에 previous_exit_type만 생략하고 나머지 필드/행 ID는 모두 일치해. |
| OPEN 종료 사유 | PASS | 25건 중 NO_EXIT_BEFORE_CUTOFF 16건, NO_PROGRESSED_BEFORE_CUTOFF 9건. 두 사유 모두 canonical·compact 공통 필드·monitor 사이에 일치해. |
| B Select / Julia / 운영 | PASS | B Select status SHA와 monitor 행, Julia ETF 보고서 73개 SHA와 monitor 행이 전후 동일해. enabled=false, effective_signal_date=PENDING_USER_APPROVAL, activation intervals=[] 유지. |
| 트랜잭션 정리 | PASS | publication journal와 transaction/staging 디렉터리 없음. Phase4D lock 파일은 남아 있어도 현재 잠금은 해제된 상태야. |
| 회귀 테스트 | PASS_SCOPED_TESTS | 관련 범위 102 passed (Phase4D/transaction/Phase4E/rebuild 93, Phase4C FAST 관련 9). 넓은 통합 실행은 무거운 로컬 KRX raw snapshot fixture에서 81 passed 후 중단했으며 전체 suite PASS로 주장하지 않아. git diff --check PASS. |
| Git commit/push | PASS | 50e0e8a2f0829df364490b2fc3b80b4414b7a678을 origin/main에 푸시했고 push 후 HEAD == origin/main, ahead/behind 0/0을 확인했어. 4,405개 allowlist 파일만 반영했고 범위 밖 staged 파일은 0개야. |
| GitHub Pages | PASS | 공개 홈페이지, 전략/종목 리포트, 섹터·외국인·ETF 페이지가 HTTP 200. 공개 monitor도 승인 digest와 요청/시장일, 1,459개 항목·423건 거래를 제공하고 identity route 대상도 HTTP 200이야. |

## 결과·운영 상태

- 게시 결과는 2026-10-08 시장 기준의 2026-10-11 요청 스냅샷이야. 오늘 매매 신호로 해석하지 않아.
- 이번 게시 성공은 실전 운영 승인과 무관해. Alignment 운영은 비활성 상태를 유지했어.
- V01의 두 차단 사유는 해결됐어: 기존 V2 게시물의 NOOP 오판정, staging 파일 수 비교로 151개 파일 삭제로 잘못 판정한 문제.
- V01 helper의 OPEN exit_type ↔ exit_reason 비교 두 지점과 회귀 테스트를 커밋에 포함했어. 공개 ETF ranking은 10/11 기준 36개, 기존 fear-index는 보호된 원본과 동일한 10/03 스냅샷이야.

## 증거 파일

- canonical_validation.json, canonical_promotion.json
- before_sha256_manifest.json, after_sha256_manifest.json, backup_sha256_manifest.json, backup_verification.json
- noop_regression.json, phase4d_dry_run.json, phase4d_live.json
- preserved_151_file_manifest.json, route_integrity.json, post_publish_readback.json
- b_select_julia_config_protection.json, regression_tests.json, validation_summary.json

- 공개 Pages 확인 URL: https://rozekurhy.github.io/krx-trend-scanner/
- 게시 커밋: 50e0e8a2f0829df364490b2fc3b80b4414b7a678
