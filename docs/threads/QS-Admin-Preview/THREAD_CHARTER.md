# QS-Admin-Preview Charter

목적:

- `/admin` 하위 내부 검토용 preview와 admin lab 페이지를 관리합니다.

담당 범위:

- analytics preview p1~p5
- analytics preview hub
- admin market briefing lab
- internal preview bundle 연결

비범위:

- 공개 페이지 반영
- admin 외 일반 사용자 노출
- Quant / QM preview 데이터 생산

대표 대상 파일:

- `service_platform/web/templates/admin*`
- `service_platform/web/analytics_preview_*`
- `service_platform/web/admin_market_lab_api.py`
- `tests/test_web`

관련 문서:

- `D:\QuantService\docs\REDBOT_3시스템_보수적운영가이드_2026-03-24.md`
- `D:\QuantService\docs\PROJECT_BRIEF.md`
- analytics handoff 관련 외부 문서들

운영 규칙:

- 모든 preview는 기본적으로 `/admin` 하위에 둡니다.
- 공개 전환 전에는 공개 메뉴/공개 route에 연결하지 않습니다.
