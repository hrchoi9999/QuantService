# QS-Quant-Handoff Charter

목적:

- Quant가 생산하는 모델/성과/변경내역/public snapshot을 QS 공개 및 admin 화면에 정확히 연결합니다.

담당 범위:

- user snapshot/model snapshot 연결
- 모델명, 모델 설명, 성과, 변경내역, compliance 문구
- canonical API 경로 정리

비범위:

- Quant 계산 로직 구현
- DB 직접 조인
- QM 시장 브리핑 payload

대표 대상 파일:

- `service_platform/web/user_snapshot_api.py`
- `service_platform/web/app.py`
- 공개 모델 페이지 템플릿
- `tests/test_web`

관련 문서:

- `D:\QuantService\docs\QUANT_WORK_REQUEST_COMPLIANCE_AUDIT_2026-03-24.md`
- `D:\QuantService\docs\QUANT_WORK_REQUEST_QUANT_MODEL_COPY_2026-03-25.md`
- Quant handoff 관련 외부 문서들
