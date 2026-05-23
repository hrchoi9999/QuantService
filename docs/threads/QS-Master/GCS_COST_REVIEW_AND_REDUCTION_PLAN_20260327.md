# Cloud Storage 비용 점검 및 절감안

작성일: 2026-03-27
관리 쓰레드: QS-Master
관련 쓰레드: QS-QM-Handoff, QS-Deploy-Ops

## 목적
- 최근 Cloud Storage 비용 증가 원인을 빠르게 좁혀서 확인한다.
- QuantService 코드/운영 구조에서 바로 줄일 수 있는 항목을 우선순위로 정리한다.
- Quant / QuantMarket 수정 없이 QS 쪽에서 먼저 손볼 수 있는 절감안을 분리한다.

## 현재 구조상 가장 의심되는 비용 원인

### 1. Cloud Build source 버킷 사용 증가
- 배포 스크립트는 매번 `gcloud builds submit`을 실행한다.
- 이때 소스 tarball이 `gs://quantservice-489808_cloudbuild/source/...` 형태로 GCS에 올라간다.
- 최근 배포 횟수가 늘었다면 저장/오퍼레이션 비용이 같이 증가할 수 있다.

근거 코드:
- [cloud_run_deploy.ps1](D:\QuantService\deploy\cloud_run_deploy.ps1)

### 2. 공개 시장 브리핑 remote handoff 재조회 증가
- 공개 시장 브리핑은 GCS current JSON을 원격으로 읽는다.
- 현재 구조는 캐시 TTL `60초` 기준이며, 캐시가 만료되면 여러 JSON 파일을 다시 GET한다.
- `cache buster(ts=...)`와 `Cache-Control: no-cache`를 함께 써서 GCS/중간 캐시 재사용을 거의 하지 않는다.
- optional payload가 늘어나면서 한 번의 reload cycle에서 읽는 파일 수가 증가했다.

근거 코드:
- [market_analysis_api.py](D:\QuantService\service_platform\web\market_analysis_api.py)

관련 포인트:
- `snapshot_cache_ttl_seconds=60`
- `_with_cache_buster(...)`
- `MARKET_ANALYSIS_FILES`
- `OPTIONAL_MARKET_ANALYSIS_KEYS`

### 3. 공개 페이지 증가에 따른 Class B GET / egress 증가
- `/`
- `/market-analysis`
- `/today`
- `/api/v1/market-analysis/*`

이 영역이 모두 remote handoff를 간접 사용하므로, 트래픽 증가 시 GCS GET과 egress 비용이 같이 늘 수 있다.

## 먼저 확인할 버킷

### 우선순위 1
- `quantservice-489808-market-analysis`

확인 이유:
- 공개 시장 브리핑 remote source current 버킷
- 최근 optional payload 추가로 읽는 파일 수 증가

### 우선순위 2
- `quantservice-489808_cloudbuild`

확인 이유:
- 배포 시 source tarball과 build 관련 object가 쌓일 수 있음
- 최근 배포 빈도 증가 영향 확인 필요

## Billing에서 먼저 볼 항목

### Cloud Storage SKU 기준
- Standard Storage
- Class A Operations
- Class B Operations
- Network Egress

### 확인 질문
1. 비용 증가가 저장 용량인지, GET/PUT 오퍼레이션인지, egress인지
2. 증가 시점이 배포 시각과 맞물리는지
3. 증가 시점이 시장 브리핑 공개 강화 시점과 맞물리는지

## 버킷별 점검 체크리스트

### A. `quantservice-489808-market-analysis`
- object 수가 급증했는가
- current 경로 외에 오래된 snapshot/object가 누적되고 있는가
- GET/Class B operations가 급증했는가
- egress가 GET 증가와 같이 늘었는가
- optional payload 추가 시점과 비용 상승 시점이 맞는가

### B. `quantservice-489808_cloudbuild`
- `source/` 아래 tarball object가 많이 남아 있는가
- build 로그/임시 object lifecycle이 없는가
- 최근 배포 횟수 증가와 비용 증가 시점이 맞는가

## QS에서 바로 손볼 수 있는 절감안

### P1. 시장 브리핑 remote cache TTL 상향
현재:
- `60초`

권장:
- `300초` 또는 `600초`

효과:
- GCS current 재조회 횟수 감소
- GET/Class B operations와 egress 감소 가능

주의:
- 최신값 반영이 1분 이내에서 5~10분 이내로 늦어질 수 있음
- 시장 브리핑 freshness 기대치와 함께 판단 필요

### P1. optional payload 조회 수 축소
현재:
- 기본 public payload 외에 optional payload 4종을 별도로 읽는다.

절감 방향:
- 홈/오늘/시장 브리핑에서 꼭 필요한 파일만 읽도록 축소
- 혹은 페이지 렌더에 실제로 필요한 optional payload만 선택적으로 로드

효과:
- remote current 파일 GET 횟수 감소

### P1. cache buster 완화 여부 검토
현재:
- `?ts=` 추가
- `Cache-Control: no-cache`
- `Pragma: no-cache`

절감 방향:
- 모든 요청에 강한 cache buster를 붙이지 않고
- TTL 내 메모리 캐시를 더 적극 활용
- 필요 시 manifest만 자주 보고, 상세 payload는 manifest 변경 시만 reload

효과:
- 같은 시점 payload 중복 fetch 감소

주의:
- 이전 stale cache 문제 재발 방지 설계 필요

### P2. manifest 중심 reload 구조로 변경
현재:
- 각 파일을 바로 remote에서 읽는다.

권장:
1. manifest만 우선 fetch
2. manifest `asof` 또는 version 변경 시에만 상세 payload refresh
3. 변경 없으면 기존 메모리 캐시 유지

효과:
- current 파일 세트 전체 재다운로드 감소

### P2. Cloud Build source 버킷 lifecycle 점검
권장:
- 오래된 source tarball 자동 삭제 lifecycle rule
- 불필요한 object 보관 기간 축소

효과:
- 저장 용량 비용 절감

주의:
- 이 항목은 운영/GCP 설정 변경이므로 QS-Deploy-Ops 주관이 적절

## 권장 실행 순서

### 1단계: 원인 확인
- Billing에서 Cloud Storage SKU 확인
- 버킷 2개(`market-analysis`, `cloudbuild`) 분리 확인
- 증가 주원인이 storage / operations / egress 중 무엇인지 판단

### 2단계: QS 빠른 절감안
- `snapshot_cache_ttl_seconds` 상향 검토
- optional payload fetch 수 축소 검토

### 3단계: 구조 개선
- manifest 중심 refresh 구조 검토
- Cloud Build source lifecycle rule 검토

## 2026-03-27 조치 결과

### 완료된 조치
- 새 asia bucket 생성:
  - `gs://quantservice-489808-cloudbuild-asia-northeast3`
- 위치:
  - `ASIA-NORTHEAST3`
- 배포 스크립트 [cloud_run_deploy.ps1](D:\QuantService\deploy\cloud_run_deploy.ps1) 전환 완료
  - Cloud Build source/log를 새 asia bucket으로 사용
- 새 bucket 기준 실제 배포 1회 성공 확인
- 기존 `US` bucket 정리 완료:
  - `gs://quantservice-489808_cloudbuild`
  - source object 삭제
  - bucket 삭제

### 현재 남은 점검
- 새 asia bucket lifecycle rule 적용 완료 (`source/` 14일, `logs/` 30일)
- Cloud Build trigger 또는 별도 수동 배포 경로가 old bucket을 참조하지 않는지 추가 점검

## 현재 QS-Master 판단
- 최근 비용 상승 원인은 `market-analysis remote current 재조회 증가`와 `배포 횟수 증가` 둘 중 하나이거나 둘 다일 가능성이 높다.
- 코드 기준으로는 특히 [market_analysis_api.py](D:\QuantService\service_platform\web\market_analysis_api.py)의
  - 짧은 TTL
  - cache buster
  - optional payload 추가
  조합이 먼저 의심된다.

## 후속 작업 권장 배정
- 비용 원인 확인: `QS-Deploy-Ops`
- remote fetch 구조 절감안 구현: `QS-QM-Handoff`
- 공개 페이지 영향 검토: `QS-Public-Web`
