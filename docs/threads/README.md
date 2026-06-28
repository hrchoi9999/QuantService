# QS Threads

`D:\QuantService\docs\threads`는 QuantService 작업을 agent 단위로 운영하기 위한 문서 허브입니다.

원칙:

- 기존 `docs` 루트 문서는 그대로 유지합니다.
- 기존 쓰레드 폴더는 기록 보존용으로 유지합니다.
- 실제 업무 배정은 `QS-Master/AGENT_OPERATING_MODEL.md`의 active agent 기준으로 합니다.
- 전체 QS 작업 운영, 릴리즈 게이트, 통합 검증 관리는 `QS-Master`가 담당합니다.

Active agent:

- `QS-Web-Platform Agent`: 공개 웹, admin preview, 인증/권한
- `QS-Handoff Agent`: Quant/QM payload 연동
- `QS-Deploy-Ops Agent`: 배포, GCS, Cloud Run, live 확인
- `QS-Master`: 작업 배정, 릴리즈 게이트, 충돌 조정

기존 기록 폴더:

- `QS-Master`
- `QS-Public-Web`
- `QS-Admin-Preview`
- `QS-Platform-Auth`
- `QS-Quant-Handoff`
- `QS-QM-Handoff`
- `QS-Deploy-Ops`

운영 규칙:

1. 새 요청은 먼저 `QS-Master/WORK_INTAKE.md` 기준으로 active agent에 배정합니다.
2. 작업 전에는 `QS-Master/AGENT_OPERATING_MODEL.md`와 관련 기존 `THREAD_CHARTER.md`를 확인합니다.
3. 작업 중 주요 결정과 커밋/배포 메모는 관련 기존 폴더 `WORKLOG.md` 또는 `QS-Master/ACTIVE_WORK_REGISTRY.md`에 남깁니다.
4. 남은 이슈와 외부 의존은 관련 기존 폴더 `BACKLOG.md`에 유지합니다.
5. 공개 반영 전에는 `QS-Master/RELEASE_GATE.md` 기준으로 통합 점검합니다.

기존 flat 문서와의 관계:

- 기존 문서는 원문 보존용입니다.
- 각 쓰레드 `THREAD_CHARTER.md`에는 관련 문서 링크 목록을 유지합니다.
- 새 작업지시문이 오면 원문은 루트 `docs` 또는 외부 handoff에 두고, 쓰레드 문서에서는 연결과 운영만 담당합니다.
