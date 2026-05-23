# QS-Public-Web Worklog

## 2026-03-26

- 공개 시장 브리핑 고도화 1차 반영
- 홈, 시장 브리핑, 오늘 페이지에 optional public payload 4종 연결
- 신규 공개 섹션:
  - 상태 타임라인
  - 모델 해석 백그라운드
  - 자산군 상대강도
  - 상태 전이 요약
- 최근 커밋:
  - `72b0173 feat: enhance public market briefing pages`

### 공개 시장 브리핑 2단 상태 표현 최종 반영

- 요청 출처: QuantMarket
- 반영 범위: 홈 / 시장 브리핑 / 오늘의 추천
- 주요 변경:
  - `정식 시장상태`와 `오늘 장중 흐름(참고용)` 2단 상태 표현 반영
  - `state_intraday_bridge.intraday_state_label` 공개 연결
  - 홈/오늘의 추천은 간단 버전, 시장 브리핑은 전체 버전 유지
- 검증:
  - `pytest tests\\test_web -q`
  - `ruff check service_platform tests`
  - `black --check service_platform tests`
- 커밋:
  - `9f0732b feat: finalize public intraday bridge labels`
- 배포:
  - Cloud Run 배포 완료
- 메모:
  - admin intraday/선물/수급 원시 데이터는 public에 노출하지 않음

## 2026-04-01

### T-series Discovery 공개 반영 완료

- 요청 출처: Quant
- 반영 범위:
  - `/` 홈 teaser
  - `/discovery` 공개 메인 화면
- 주요 변경:
  - T-series Discovery 공개 섹션/탭 UI 반영
  - Stock / ETF 탭
  - confirmed / near / observe bucket table
  - shadow summary table
  - empty bucket fallback 유지
- 검증:
  - `pytest tests\test_web -q`
  - `ruff check service_platform tests`
  - `black --check service_platform tests deploy`
  - live `/`, `/discovery` 확인 완료
- 배포 커밋:
  - `df90823 feat: deploy T-series Discovery public pages`
  - `f746aae fix: normalize legacy T-series shadow summary`
- 메모:
  - 기존 S-series 페이지/데이터 영향 없음
