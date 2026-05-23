# QS Active Work Registry

| 영역 | 대표 쓰레드 | 현재 상태 | 최근 메모 |
|---|---|---|---|
| 공개 웹 | QS-Public-Web | 완료 | T-series Discovery 공개 반영 완료 (`df90823`, `f746aae`) |
| 관리자 preview | QS-Admin-Preview | 활성 | analytics p1~p5, market briefing lab 운영 검토 가능 |
| 인증/플랫폼 | QS-Platform-Auth | 유지보수 | 관리자 로그인, bootstrap, CSRF/권한 보강 반영 완료 |
| Quant 연동 | QS-Quant-Handoff | 활성 | 모델 copy/compliance/weekly model 관련 upstream 필드 반영 중 |
| QM 연동 | QS-QM-Handoff | 활성 | public market briefing optional payload, admin lab payload 연동 중 |
| 배포/운영 | QS-Deploy-Ops | 활성 | Cloud Run/GCS remote handoff 운영 유지, Cloud Build bucket asia 전환 완료 |

현재 대화 쓰레드:

- `QS-Public-Web`

운영 메모:

- 새 요청은 먼저 `QS-Master` 기준으로 대표 쓰레드를 정한 뒤 처리합니다.
- 공개와 admin preview가 동시에 걸리는 요청은 `QS-Master`가 릴리즈 게이트를 주관합니다.

## 2026-03-26

### 공개 시장 브리핑 2단 상태 표현 최종 반영 완료

- 요청 출처: QuantMarket
- 대표 쓰레드: QS-Public-Web
- 협업 쓰레드: QS-QM-Handoff
- 배포 커밋: `9f0732b feat: finalize public intraday bridge labels`
- 상태: 완료

핵심 결과:

- 공개 3페이지(`/`, `/market-analysis`, `/today`)에 `정식 시장상태` + `오늘 장중 흐름(참고용)` 2단 표현 반영 완료
- `state_intraday_bridge.intraday_state_label`을 그대로 사용하도록 연결 완료
- `display_label`, `bridge_text`, `basis_lines` 유지 확인
- admin intraday/선물/수급 원시 데이터의 public 노출 없음 확인

검증:

- `pytest tests\\test_web -q`
- `ruff check service_platform tests`
- `black --check service_platform tests`
- live HTML 확인 완료

남은 이슈:

- 없음

## 2026-04-01

### T-series Discovery 공개 반영 완료

- 요청 출처: Quant
- 대표 쓰레드: QS-Quant-Handoff, QS-Public-Web
- 배포 상태: 완료
- 배포 커밋:
  - `df90823 feat: deploy T-series Discovery public pages`
  - `f746aae fix: normalize legacy T-series shadow summary`

핵심 결과:

- 홈(`/`)에 T-series Discovery teaser 공개 반영 완료
- `/discovery` 공개 메인 화면 공개 반영 완료
- `Stock` / `ETF` 탭 정상 노출
- `confirmed / near / observe` bucket 정상 렌더
- ETF `shadow_summary` bucket map 정합성 보정 완료
- 기존 S-series 페이지와 API 영향 없음 확인

운영 확인:

- `SNAPSHOT_SOURCE=remote`
- `SNAPSHOT_GCS_BASE_URL=https://storage.googleapis.com/quantservice-489808-market-analysis`
- `/api/v1/discovery/t-series` source_name=`handoff:tseries_discovery_current`

남은 이슈:

- 없음
