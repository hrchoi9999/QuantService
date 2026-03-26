# QS-QM-Handoff Charter

목적:

- QuantMarket이 생산하는 시장 브리핑 public/admin payload를 QS에서 소비하고 연결합니다.

담당 범위:

- public market briefing current/GCS current
- optional public payload
- admin market briefing lab payload
- remote handoff, manifest, fallback, public/admin 분리

비범위:

- QM 시장 계산/AI 브리핑 생성
- 장중 데이터 생산 로직

대표 대상 파일:

- `service_platform/web/market_analysis_api.py`
- `service_platform/web/admin_market_lab_api.py`
- `service_platform/web/app.py`
- market-analysis 관련 템플릿
- `tests/test_web`

관련 문서:

- `D:\QuantService\docs\QUANTMARKET_WORK_REQUEST_2026-03-24.md`
- `D:\QuantService\docs\QUANTMARKET_WORK_REQUEST_COMPLIANCE_AUDIT_2026-03-24.md`
- `D:\QuantService\docs\QUANTMARKET_WORK_REQUEST_MARKET_BRIEF_COPY_2026-03-25.md`
- QM market briefing handoff 관련 외부 문서들
