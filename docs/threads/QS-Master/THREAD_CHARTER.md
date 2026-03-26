# QS-Master Charter

목적:

- QuantService 전체 쓰레드 운영의 총괄 허브
- 작업 배정, 통합 검증, 릴리즈 게이트, 외부 요청서 판단 담당

책임 범위:

- 새 요청의 쓰레드 배정
- 공개/관리자/플랫폼/외부연동 범위 구분
- 공개 배포 전 최종 릴리즈 게이트 운영
- 각 쓰레드의 검증 결과 취합
- Quant / QM 추가 요청 필요 여부 판단
- 운영 반영 여부, GitHub 반영 여부 기록

비범위:

- 개별 기능 구현의 상세 설계 주도
- Quant / QM 코드 직접 수정
- 런타임 데이터 생산 로직 구현

승인 관계:

- `QS-Public-Web` 공개 반영은 `QS-Master` 게이트 확인 후 배포
- `QS-Admin-Preview`는 공개 연결 전 `QS-Master` 승인 필요
- `QS-Platform-Auth` 변경은 보안/권한 검증 포함해 `QS-Master` 기록 필요

관련 문서:

- `D:\QuantService\docs\REDBOT_통합_마스터_Codex_지시문_2026-03-24.md`
- `D:\QuantService\docs\REDBOT_3시스템_보수적운영가이드_2026-03-24.md`
- `D:\QuantService\docs\RUNBOOK.md`
- `D:\QuantService\docs\RUNBOOK_OPS.md`

현재 기본값:

- 현재 대화 쓰레드: `QS-Public-Web`
- QS 전체 운영 총괄: `QS-Master`
- 코드 구조는 유지하고 문서 운영만 쓰레드 체계로 관리
