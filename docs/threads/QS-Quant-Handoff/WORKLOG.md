# QS-Quant-Handoff Worklog

## 2026-03-26

- upstream quant model copy fields 우선 사용 반영
- compliance wording / model snapshot canonical route 반영 완료
- 최근 커밋:
  - `419c97a feat: use upstream quant model copy fields`
  - `3eed72b feat: align public model snapshots with compliance wording`

## 2026-04-01

### T-series Discovery remote current 계약 및 공개 연동 완료

- 요청 출처: Quant
- 반영 범위:
  - T-series discovery remote-first loader
  - remote current 계약 정리
  - payload schema 정합성 확인
- 최종 remote current:
  - `https://storage.googleapis.com/quantservice-489808-market-analysis/tseries_discovery/current/quantservice_tseries_discovery.json`
- 운영 설정:
  - `SNAPSHOT_SOURCE=remote`
  - `SNAPSHOT_GCS_BASE_URL=https://storage.googleapis.com/quantservice-489808-market-analysis`
- 후속 조치:
  - ETF `shadow_summary` bucket map 정규화 확인 완료
- 배포 커밋:
  - `f746aae fix: normalize legacy T-series shadow summary`
- 메모:
  - public loader / UI 계약 fully aligned
