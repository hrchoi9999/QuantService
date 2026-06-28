# QS Active Work Registry

| 영역 | Active agent | 현재 상태 | 최근 메모 |
|---|---|---|---|
| 공개 웹 / admin / auth | QS-Web-Platform Agent | 활성 | `QS-Public-Web`, `QS-Admin-Preview`, `QS-Platform-Auth` 병합 운영 |
| Quant / QM handoff | QS-Handoff Agent | 활성 | `QS-Quant-Handoff`, `QS-QM-Handoff` 병합 운영 |
| 배포/운영 | QS-Deploy-Ops Agent | 활성 | Cloud Run/GCS remote handoff 운영 유지, Cloud Build bucket asia 전환 완료 |
| 총괄 / release gate | QS-Master | 활성 | 요청 분류, owner/reviewer agent 지정, 공개 반영 판단 |

현재 대화 역할:

- `QS-Master`

운영 메모:

- 새 요청은 먼저 `QS-Master/WORK_INTAKE.md` 기준으로 active agent에 배정합니다.
- 공개와 admin preview가 동시에 걸리는 요청은 `QS-Web-Platform Agent`가 owner, `QS-Master`가 release gate를 담당합니다.
- Quant/QM 산출물 계약과 공개 UI가 동시에 걸리면 `QS-Handoff Agent`가 owner, `QS-Web-Platform Agent`가 reviewer입니다.
- 배포가 필요한 작업은 구현 agent 완료 후 `QS-Deploy-Ops Agent`에 넘깁니다.

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
