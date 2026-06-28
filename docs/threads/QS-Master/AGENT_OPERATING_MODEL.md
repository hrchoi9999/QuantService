# QS Agent Operating Model

목적:

- QS-Master가 모든 작업을 직접 수행하지 않고, 요청을 active agent 단위로 배정하기 위한 운영 기준입니다.
- 기존 `QS-*` 쓰레드 폴더는 기록 보존용으로 유지하고, 실제 업무 배정은 아래 active agent 기준으로 합니다.

## Active agents

| Agent | 병합 대상 | 책임 |
|---|---|---|
| QS-Web-Platform Agent | `QS-Public-Web`, `QS-Admin-Preview`, `QS-Platform-Auth` | 공개 웹, admin preview, 인증/권한/보안 UI 경계 |
| QS-Handoff Agent | `QS-Quant-Handoff`, `QS-QM-Handoff` | Quant/QM payload 계약, remote current 연결, public/admin 데이터 경계 |
| QS-Deploy-Ops Agent | `QS-Deploy-Ops` | Cloud Run, GCS, env, live 확인, 배포/운영 점검 |
| QS-Master | `QS-Master` | 요청 분류, agent 배정, release gate, 충돌 조정 |

## 병합 판단

- `QS-Admin-Preview`와 `QS-Platform-Auth`는 backlog가 작고 대부분 `service_platform/web` 경로를 공유하므로 `QS-Web-Platform Agent`로 병합합니다.
- `QS-Quant-Handoff`와 `QS-QM-Handoff`는 외부 생산 시스템은 다르지만 QS 안에서는 payload 소비/검증/표현 계약 업무이므로 `QS-Handoff Agent`로 병합합니다.
- `QS-Deploy-Ops`는 배포 권한, 운영 env, GCS/Cloud Run 확인이 걸려 있으므로 독립 agent로 유지합니다.
- `QS-Master`는 구현을 기본 담당하지 않고 배정, 검증 기준, 공개 반영 판단만 담당합니다.

## Assignment rules

1. 공개/관리자 화면, 카피, 템플릿, auth/access 변경은 `QS-Web-Platform Agent`에 배정합니다.
2. Quant 또는 QuantMarket 산출물 계약, schema, current URL, fallback, public/admin 데이터 분리는 `QS-Handoff Agent`에 배정합니다.
3. 배포, 운영 URL 확인, Cloud Run/GCS/env, 비용/인프라 점검은 `QS-Deploy-Ops Agent`에 배정합니다.
4. 두 agent 이상이 걸리면 `QS-Master`가 owner agent 1개와 reviewer agent 1개를 지정합니다.
5. 공개 반영 전에는 항상 `QS-Master/RELEASE_GATE.md` 기준으로 최종 확인합니다.

## Reporting contract

각 agent는 작업 완료 시 아래만 보고합니다.

- 담당 agent
- 변경 범위
- 검증 결과
- public/admin 경계 영향
- 배포 필요 여부
- 후속 요청이 필요한 외부 thread

