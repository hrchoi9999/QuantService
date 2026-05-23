# QS-Deploy-Ops Worklog

기록 항목:

- 배포 대상 커밋
- 배포 시각
- 환경변수 변경
- live 확인 URL
- 장애/실패 메모

## 2026-03-26

- market briefing public optional payload 공개 배포 완료
- admin preview 운영 연결 유지
- GCS remote market current 읽기 구조 유지
- 최근 커밋/반영:
  - `72b0173 feat: enhance public market briefing pages`
  - Cloud Run image `20260326-181616`
- 공개 시장 브리핑 2단 상태 표현 운영 배포 완료
- 배포 대상 커밋:
  - `83bc685 feat: deploy dual-stage market state display`
- 배포 시각:
  - `2026-03-26 22:00~22:04 KST`
- Cloud Run 반영:
  - image `asia-northeast3-docker.pkg.dev/quantservice-489808/quantservice/web:20260326-220022`
  - revision applied to `quantservice-web`
- 환경변수 변경:
  - 없음
- live 확인 URL:
  - `https://redbot.co.kr/`
  - `https://redbot.co.kr/market-analysis`
  - `https://redbot.co.kr/today`
- live 확인 메모:
  - 세 페이지 모두 신규 2단 상태 표현용 마크업/CSS 응답 확인
  - 홈과 오늘의 추천은 compact/bridge 버전으로 간단 반영 확인
  - 시장 브리핑은 `display_label`, `bridge_text`, `basis_lines` 노출 확인
  - 잔여 이슈: 현재 public payload에 `intraday_state_label`이 없고 `intraday.direction_label`만 있어 두 번째 막대는 미노출

### 공개 시장 브리핑 2단 상태 표현 최종 배포

- 배포 대상: `/`, `/market-analysis`, `/today`
- 배포 커밋:
  - `9f0732b feat: finalize public intraday bridge labels`
- 배포 시각:
  - `2026-03-26 22:15~22:20 KST`
- 환경변수 변경:
  - 없음
- live 확인:
  - `/` 200, 두 번째 막대 노출 확인
  - `/market-analysis` 200, 두 번째 막대 노출 확인
  - `/today` 200, 두 번째 막대 노출 확인
- 추가 확인:
  - `display_label`, `bridge_text`, `basis_lines` 정상 유지
  - 홈과 오늘의 추천은 간단 버전, 시장 브리핑은 전체 버전으로 정상 반영
  - public HTML 기준 admin intraday/선물/수급 원시 데이터 노출 없음
- 상태:
  - 완료

## 2026-03-27

### Cloud Build bucket asia 전환 및 old us bucket 정리

- 배경:
  - 기존 Cloud Build source bucket `gs://quantservice-489808_cloudbuild`가 `US` 리전이어서
    asia 리전 서비스 운영 관점에서 비용/지연 비효율 가능성이 있었습니다.
- 조치:
  - 새 bucket 생성:
    - `gs://quantservice-489808-cloudbuild-asia-northeast3`
  - 위치:
    - `ASIA-NORTHEAST3`
  - 배포 스크립트 [cloud_run_deploy.ps1](D:\QuantService\deploy\cloud_run_deploy.ps1) 수정
    - `--gcs-source-staging-dir gs://quantservice-489808-cloudbuild-asia-northeast3/source`
    - `--gcs-log-dir gs://quantservice-489808-cloudbuild-asia-northeast3/logs`
  - 새 bucket 기준 실제 배포 1회 성공 확인
  - 기존 bucket `gs://quantservice-489808_cloudbuild` 객체 삭제 및 bucket 삭제 완료
- 확인:
  - 새 bucket describe 결과: `ASIA-NORTHEAST3`
  - 기존 bucket describe 결과: `404 not found`
- 운영 메모:
  - 앞으로 `deploy\\cloud_run_deploy.ps1` 기준 배포는 새 asia bucket을 사용합니다.
  - 별도 Cloud Build trigger나 다른 수동 build 경로가 있으면 별도 점검이 필요합니다.

### Cloud Build bucket asia 전환 후속 운영 점검

- 점검 시각:
  - `2026-03-27 KST`
- 새 bucket 상태:
  - `gs://quantservice-489808-cloudbuild-asia-northeast3`
  - location `ASIA-NORTHEAST3`
  - lifecycle rule: 아직 없음
  - soft delete policy: 기본 `7일`
- trigger/경로 점검:
  - `gcloud builds triggers list` 결과: `[]`
  - 로컬 배포 스크립트/문서 외 old bucket 직접 참조는 운영 문서 기록을 제외하면 없음
  - 최근 build 메타데이터 확인 결과 최신 build는 source/log 모두 새 asia bucket 사용
- 최근 build 확인:
  - latest build id `425f74b1-44f0-4283-a042-373902b6048e`
  - source bucket `quantservice-489808-cloudbuild-asia-northeast3`
  - logs bucket `gs://quantservice-489808-cloudbuild-asia-northeast3/logs`
- 운영 판단:
  - source tarball은 재현 목적이 짧아 `7일` 자동 삭제 lifecycle 권장
  - build logs는 장애 역추적 여지를 위해 `30일` 자동 삭제 lifecycle 권장
  - 현재 trigger는 없어 old `US` bucket 재참조 위험은 낮음
- 운영 체크리스트 반영:
  - 배포 후 최근 Cloud Build 1건의 `source.storageSource.bucket` 확인
  - 배포 후 최근 Cloud Build 1건의 `logsBucket` 확인
  - 월간 Billing에서 Cloud Storage SKU 중 Standard Storage / Class A / Class B / Egress 추세 확인
  - 새 asia bucket object 증가 추세와 lifecycle 적용 여부 확인

### HSTS 적용 및 HTTP 80 제거 사전 준비 완료

- 배경:
  - Networking 비용의 주원인이 `Cloud Load Balancer Forwarding Rule Minimum Global`로 확인됨
  - 현재 global forwarding rule 2개 운영 중
    - `bluebot-http-forwarding-rule` (80)
    - `bluebot-https-forwarding-rule` (443)
  - `redbot.co.kr`는 global LB IP `35.186.251.170` 사용 중
  - Cloud Run direct domain mapping은 `asia-northeast3`에서 생성 불가
- 이번 반영:
  - 앱 레벨 HTTPS 응답에 `Strict-Transport-Security: max-age=2592000` 추가
  - global LB backend service `bluebot-backend-service`에도 동일 HSTS 헤더 추가
  - 운영 배포 완료 및 live 확인 완료
- live 확인 기준:
  - `https://redbot.co.kr` -> `Strict-Transport-Security: max-age=2592000`
  - `https://quantservice-web-452568862306.asia-northeast3.run.app` -> `Strict-Transport-Security: max-age=2592000`
- 운영 메모:
  - 현재 단계에서는 `bluebot-http-forwarding-rule` 제거는 미진행
  - LB 자체는 유지 필요, 장기 절감 후보는 `80` 포트 forwarding rule 제거 여부
  - HSTS 안정 적용이 유지되는지 후속 모니터링 필요
- 향후 80 포트 rule 제거 검토 시 체크:
  - `http://redbot.co.kr` 직접 유입 영향
  - 사용자 불편 감수 가능 여부
  - 운영/브랜드 정책 적합성

### Cloud Build asia bucket lifecycle rule 적용

- 대상 bucket:
  - `gs://quantservice-489808-cloudbuild-asia-northeast3`
- 적용 정책:
  - `source/` 아래 object: `14일` 후 자동 삭제
  - `logs/` 아래 object: `30일` 후 자동 삭제
- 정책 파일:
  - [cloudbuild_bucket_lifecycle.json](D:\QuantService\deploy\cloudbuild_bucket_lifecycle.json)
- 목적:
  - Cloud Build source tarball과 로그 object가 불필요하게 장기 누적되지 않도록 관리

### User Snapshot Public Data Remote Current 전환 운영 준비

- 배경:
  - 운영 Cloud Run은 현재 `MARKET_ANALYSIS_SOURCE=remote`, `SNAPSHOT_SOURCE=local`
  - 시장 브리핑은 원격 current를 보지만, 모델 기준안/성과/변경내역은 stale local current 의존
- 확인:
  - `deploy/cloud_run_deploy.ps1`는 기존에 `SNAPSHOT_SOURCE`만 전달하고 있었음
  - 이번 준비에서 `SNAPSHOT_GCS_BASE_URL`도 deploy env로 전달 가능하도록 정리
  - `.env.example`에 remote current 전환 예시 추가
  - [DEPLOYMENT.md](D:\QuantService\docs\DEPLOYMENT.md)에 전환 절차와 live 확인 포인트 추가
- 구현 경계 메모:
  - `SnapshotDataProvider`는 `gcs-current` 지원
  - 하지만 public user snapshot 경로는 아직 `UserSnapshotMockApi`를 사용하며 local directory 기반
  - 따라서 env wiring만으로는 즉시 전환되지 않으며 `QS-Quant-Handoff` 구현 완료가 선행 조건
- 배포 후 확인 예정:
  - `/api/v1/model-snapshots/today`
  - `/`
  - `/today`
  - `/performance`
  - `/changes`
  - latest `as_of_date` / `generated_at`
  - stale local 미노출 여부
  - remote current 실패 시 fallback 동작

### T-series Discovery 공개 반영 배포

- 배포 대상 커밋:
  - `df90823 feat: deploy T-series Discovery public pages`
  - `f746aae fix: normalize legacy T-series shadow summary`
- 배포 시각:
  - 1차 배포: `2026-04-01 12:05 KST`
  - hotfix 재배포: `2026-04-01 12:29 KST`
- 환경변수 변경:
  - `SNAPSHOT_SOURCE=remote`
  - `SNAPSHOT_GCS_BASE_URL=https://storage.googleapis.com/quantservice-489808-market-analysis`
- live 확인 URL:
  - [home](https://redbot.co.kr/)
  - [discovery](https://redbot.co.kr/discovery)
  - [today](https://redbot.co.kr/today)
  - [performance](https://redbot.co.kr/performance)
  - [changes](https://redbot.co.kr/changes)
  - [discovery api](https://redbot.co.kr/api/v1/discovery/t-series)
- 확인 결과:
  - 홈 `T-series Discovery` teaser 노출 확인
  - `/discovery`에서 `Stock` / `ETF` 탭, `confirmed / near / observe` bucket 렌더 확인
  - ETF remote payload의 legacy `historical_stage1` / `historical_stage2` shadow summary를 public loader에서 `near` / `confirmed`로 호환 매핑하도록 hotfix 반영
  - `현재 후보가 없습니다.` empty-state 노출 확인
  - 기존 S-series `/today`, `/performance`, `/changes`, `/api/v1/model-snapshots/today` 200 응답 확인
- 장애/실패 메모:
  - 1차 live 확인에서 remote ETF `shadow_summary`가 legacy key로 publish되어 public UI에 빈 값으로 보였음
  - `f746aae` hotfix 배포 후 `confirmed.obs_n=69`, `near.obs_n=698` live 반영 확인

### T-series Discovery 공개 배포 완료

- 배포 상태: 완료
- 배포 커밋:
  - `df90823 feat: deploy T-series Discovery public pages`
  - `f746aae fix: normalize legacy T-series shadow summary`
- 운영 env 확인:
  - `SNAPSHOT_SOURCE=remote`
  - `SNAPSHOT_GCS_BASE_URL=https://storage.googleapis.com/quantservice-489808-market-analysis`
- live 확인:
  - `/` 200, T-series Discovery teaser 확인
  - `/discovery` 200, Stock / ETF 탭 확인
  - bucket 렌더 확인
  - empty bucket fallback 확인
  - ETF `shadow_summary` 확인
  - `/api/v1/discovery/t-series` source_name=`handoff:tseries_discovery_current`
- 추가 확인:
  - 기존 S-series 영향 없음
    - `/today`
    - `/performance`
    - `/changes`
    - `/api/v1/model-snapshots/today`

### T-series Discovery 성능요약 UI 공개 배포

- 배포 대상 커밋:
  - `0a54be6 feat: add T-series performance summary UI`
- 배포 시각:
  - `2026-04-01 14:37 KST`
- 환경변수 유지:
  - `SNAPSHOT_SOURCE=remote`
  - `SNAPSHOT_GCS_BASE_URL=https://storage.googleapis.com/quantservice-489808-market-analysis`
- live 확인 URL:
  - [discovery](https://redbot.co.kr/discovery)
  - [stock api](https://redbot.co.kr/api/v1/discovery/t-series/T-STOCK-V01)
  - [etf api](https://redbot.co.kr/api/v1/discovery/t-series/T-ETF-V01)
  - [home](https://redbot.co.kr/)
  - [today api](https://redbot.co.kr/api/v1/model-snapshots/today)
- 확인 결과:
  - `/discovery`에서 `성과 요약`, `primary_period`, `Total Return`, `CAGR`, `MDD`, `Sharpe`, `period_metrics` 테이블 노출 확인
  - 안내 문구와 기존 `confirmed / near / observe` 영역, `그림자 추적 요약` 섹션 공존 확인
  - `T-STOCK-V01`, `T-ETF-V01` API 모두 `performance_summary` 포함 확인
  - 홈 teaser 유지, 기존 S-series `/today` 및 `/api/v1/model-snapshots/today` 200 응답 확인
- 장애/실패 메모:
  - 없음

### 공개 시장 관련 페이지 내일 시장 전망 참고 반영 배포

- 배포 대상 커밋:
  - `d56b464 feat: add public market next-day preview`
- 배포 시각:
  - `2026-04-01 17:58 KST`
- 환경변수 확인:
  - `SNAPSHOT_SOURCE=remote`
  - `SNAPSHOT_GCS_BASE_URL=https://storage.googleapis.com/quantservice-489808-market-analysis`
- live 확인 URL:
  - [home](https://redbot.co.kr/)
  - [market-analysis](https://redbot.co.kr/market-analysis)
  - [today](https://redbot.co.kr/today)
  - [next-day-preview api](https://redbot.co.kr/api/v1/market-analysis/next-day-preview)
- 확인 결과:
  - Cloud Run 배포 성공, image `asia-northeast3-docker.pkg.dev/quantservice-489808/quantservice/web:20260401-175541` 반영 확인
  - `/api/v1/market-analysis/next-day-preview` 200 응답 확인
  - API payload 기준 `active_now=false`, `preview_label=혼조 출발 가능성`, `reference_session=2026-04-02` 확인
  - `/`, `/market-analysis`, `/today` 모두 기존 `퀀트모델 시장 흐름` / `오늘 장중 흐름` 유지 확인
  - `active_now=false` 조건에 따라 `내일 시장 전망 참고` 카드/보조 라인은 세 페이지에서 미노출 확인
  - live `pages.css`에 `market-next-day-*` 스타일과 모바일 clamp 규칙 반영 확인
  - 기존 `/performance`, `/changes` 200 응답 확인
- 장애/실패 메모:
  - 없음

### 공개 내일 시장 전망 참고 카드 야간 핵심 자산 노출 보완 배포

- 배포 대상 커밋:
  - `ae53b18 feat: expose overnight assets in next-day preview`
- 배포 시각:
  - `2026-04-01 20:58 KST`
- 환경변수 확인:
  - `SNAPSHOT_SOURCE=remote`
  - `SNAPSHOT_GCS_BASE_URL=https://storage.googleapis.com/quantservice-489808-market-analysis`
- live 확인 URL:
  - [home](https://redbot.co.kr/)
  - [market-analysis](https://redbot.co.kr/market-analysis)
  - [today](https://redbot.co.kr/today)
  - [next-day-preview api](https://redbot.co.kr/api/v1/market-analysis/next-day-preview)
- 확인 결과:
  - Cloud Run 배포 성공, image `asia-northeast3-docker.pkg.dev/quantservice-489808/quantservice/web:20260401-205659` 반영 확인
  - `/api/v1/market-analysis/next-day-preview` 200 응답 확인
  - API payload 기준 `active_now=true`, `preview_label=혼조 출발 가능성` 확인
  - `/`, `/market-analysis`, `/today` 모두 `내일 시장 전망 참고` 노출 확인
  - `코스피200 야간선물` 노출 확인, 같은 화면에서 `한국 관련 야간 프록시` 미노출 확인
  - `KOSPI200_NIGHT_FUT` 존재 시 EWY보다 우선 노출되는 동작 live 확인
  - `/market-analysis` full 카드에서 `코스피200 야간선물`, `S&P500 선물`, `원달러` 3개 핵심 자산 렌더 확인
  - 홈은 1줄 보조 라인, `/today`는 compact 카드와 mini 카드 동시 노출 확인
  - 기존 `퀀트모델 시장 흐름` / `오늘 장중 흐름` 레이어 유지 확인
  - live `pages.css`에서 `market-next-day-asset-grid`, `market-next-day-inline-assets`, 모바일 clamp 규칙 반영 확인
- 장애/실패 메모:
  - 없음
