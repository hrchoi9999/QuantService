# QS-Deploy-Ops Charter

목적:

- QuantService 운영 반영, 배포, 환경변수, live 확인을 관리합니다.

담당 범위:

- Cloud Run 배포
- GCS current 연결
- 환경변수 반영
- live HTML/API 확인
- 배포 실패 원인 점검
- 운영 반영 체크리스트 관리

비범위:

- 기능 자체의 제품 의사결정
- 기능 구현 자체
- Quant / QM 데이터 생산

대표 대상 파일:

- `deploy/cloud_run_deploy.ps1`
- `.env.example`
- 운영 관련 docs

관련 문서:

- `D:\QuantService\docs\DEPLOYMENT.md`
- `D:\QuantService\docs\GCP_DEPLOY.md`
- `D:\QuantService\docs\RUNBOOK_OPS.md`

운영 원칙:

- 기능 구현은 다른 쓰레드에서 진행하고, 이 쓰레드는 운영 반영과 확인을 담당합니다.
- 배포 전에는 대표 쓰레드의 검증 결과를 확인합니다.
- 공개 반영은 `QS-Master` 릴리즈 게이트 기준으로 최종 점검 후 진행합니다.
- 운영 이슈는 원인과 영향 범위를 기록하고, 필요 시 담당 쓰레드로 다시 넘깁니다.

작업 기록 기준:

- 배포 대상 커밋
- 배포 시각
- 환경변수 변경
- live 확인 URL
- 장애/실패 메모
