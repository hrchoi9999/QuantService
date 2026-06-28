# QuantService 자동실행 작업 이관 수요조사 회신

- 작성일: 2026-05-23
- 작성 쓰레드: QuantService
- 수신 대상: QuantOpsScheduler
- 기준 요청서: `D:\QuantOpsScheduler\state\work-requests\20260522-154012-all-threads-automation-transfer-survey.md`

## 1. 기본 정보

- 대상 쓰레드/프로젝트명: QuantService
- 작업 폴더: `D:\QuantService`
- 담당 목적:
  - redbot.co.kr 웹서비스 코드/템플릿/API/배포 스크립트 관리
  - Quant/QuantMarket이 생산한 current JSON payload를 웹서비스 fallback 데이터로 보관
  - Cloud Run 배포 스크립트 및 운영 문서 관리
- 현재 자동실행 여부: ACTIVE 추정
  - 기존 백업 로그 기준 `21:00 KST` 반복 실행 흔적 있음
  - Windows Task Scheduler 등록명은 QuantService 쓰레드에서 명확히 확인하지 못함
  - QuantOpsScheduler 통합 자동실행 완료 고지 전까지 기존 자동실행은 중지하지 말 것

## 2. 자동실행 작업 목록

### 작업 A

- 작업 이름: QuantService 로컬 작업폴더 백업
- 작업 ID 또는 기존 자동실행 ID:
  - 기존 Task Scheduler ID 미확인
  - 기존 실행 흔적: `D:\QuantBackup\logs\quantservice_backup_*.log`
  - 신규 표준 실행 위치: `D:\QunatBackup\QuantService`
- 실행 주기: 매일 1회 권장
- 실행 시간대: `Asia/Seoul`
- 실행 희망 시각: `21:00 KST`
- 실행 조건:
  - `D:\QuantService` 경로가 존재할 것
  - `D:\QunatBackup\QuantService`에 쓰기 가능할 것
  - 이전 실행 중인 백업 프로세스가 없을 것
  - Git 작업 중 대량 파일 stage/commit/push 중이면 실행을 피할 것
- 실행 명령:
  - 권장:
    - `D:\QunatBackup\QuantService\run_quantservice_backup.cmd`
  - 직접 실행:
    - `powershell.exe -NoProfile -ExecutionPolicy Bypass -File "D:\QunatBackup\QuantService\backup_quantservice.ps1" -SourcePath "D:\QuantService" -BackupRoot "D:\QunatBackup\QuantService" -KeepLatest 1 -Verify`
- 작업 디렉터리: `D:\QuantService`
- 사용하는 Python/venv/도구:
  - Python 불필요
  - PowerShell
  - `robocopy`
  - .NET `System.IO.Compression.FileSystem`
  - `git` command line: 백업 metadata의 `git_head` 기록용
- 필요한 입력 파일:
  - `D:\QuantService` 전체 파일 트리
  - 제외 디렉터리:
    - `.git`
    - `.venv`
    - `.venv_32_backup`
    - `.pytest_cache`
    - `.ruff_cache`
    - `__pycache__`
    - `htmlcov`
- 읽는 DB/테이블:
  - 직접 DB 쿼리 없음
  - 파일 백업 대상에 존재하면 `data/*.db` 등 런타임 DB 파일은 복사될 수 있음
- 쓰는 DB/테이블: 없음
- 수정/생성하는 파일:
  - `D:\QunatBackup\QuantService\QuantService_yyyyMMdd_HHmmss.zip`
  - `D:\QunatBackup\QuantService\latest_backup.txt`
  - `D:\QunatBackup\QuantService\logs\quantservice_backup_yyyyMM.log`
  - 임시 staging:
    - `D:\QunatBackup\QuantService\_staging\QuantService_yyyyMMdd_HHmmss`
    - 정상 완료 시 삭제되어야 함
- 외부 API/네트워크 의존성: 없음
- 정상 완료 판단 기준:
  - `latest_backup.txt`가 갱신됨
  - `latest_backup.txt`의 `git_head`가 실행 시점의 `D:\QuantService` HEAD와 일치함
  - 최신 `QuantService_*.zip` 파일이 생성됨
  - 로그에 `Backup completed`가 기록됨
  - `D:\QunatBackup\QuantService\_staging` 아래 실행별 staging 폴더가 남지 않음
- 실패 판단 기준:
  - PowerShell/robocopy exit code 오류
  - `latest_backup.txt` 미갱신
  - zip 미생성 또는 0 byte
  - `_staging\QuantService_*` 폴더 잔존
  - 로그에 `Backup failed` 기록
- 실패 시 사용자에게 알려야 하는 조건:
  - 백업 생성 실패
  - 2회 연속 실패
  - 최신 백업 age가 26시간 초과
  - `git_head`가 `unknown`으로 기록됨
  - zip 크기가 직전 정상 백업 대비 50% 이상 급감
  - `D:\QunatBackup\QuantService` 여유 공간 부족
- 평균 실행 시간:
  - 최근 실행 기준 약 수 초
  - 파일 수/JSON payload 크기에 따라 1분 내외까지 허용
- 중복 실행 허용 여부: 불허
  - 같은 `BackupRoot`에 `_staging`과 zip 생성이 겹치면 결과가 불안정할 수 있음

## 3. 최종 산출물 요구사항

- 산출물 이름: QuantService 로컬 백업 ZIP
- 산출물 형식: ZIP / TXT / LOG
- 산출물 현재 위치:
  - 신규 기준: `D:\QunatBackup\QuantService`
  - 과거 위치: `D:\QuantBackup`
  - 2026-05-23 기준 기존 `QuantService_*.zip`은 신규 위치로 이동 완료
- 허브에 공유해야 할 위치:
  - `D:\QunatBackup\QuantService\latest_backup.txt`
  - `D:\QunatBackup\QuantService\logs\quantservice_backup_yyyyMM.log`
  - 최신 `D:\QunatBackup\QuantService\QuantService_*.zip`
- 최신 상태 판정 기준:
  - `latest_backup.txt`의 `backup_created_at`이 26시간 이내
  - `latest_backup.txt`의 `git_head`가 `D:\QuantService` 현재 HEAD 또는 허용된 최신 커밋과 일치
  - 최신 ZIP 파일 존재 및 size > 1MB
- 보존 기간:
  - `KeepLatest=1`
  - 최신 ZIP 1개와 해당 `.sha256` 1개만 유지
  - 이전 `QuantService_*.zip`과 해당 `.sha256`은 백업 성공 후 삭제
- 후속 소비 쓰레드:
  - QuantOpsScheduler
  - QuantService
- 후속 소비 방식:
  - QuantOpsScheduler는 `latest_backup.txt`와 로그를 읽어 상태 요약
  - 복구가 필요할 때는 QuantService 쓰레드에 별도 작업 요청

## 4. 허브 이관 가능 범위

- 선택: 허브가 실행 로그만 수집
- 선택: 허브가 최종 산출물만 수집
- 선택: 허브가 실행 요청서를 만들고 실제 실행은 해당 쓰레드에서 수행

권장 운영안:

- 1단계:
  - QuantOpsScheduler가 `latest_backup.txt`와 로그만 감시
  - 기존 QuantService 자동실행은 유지
- 2단계:
  - QuantOpsScheduler에서 동일 명령으로 백업 실행을 통합 등록
  - QuantOpsScheduler가 통합 자동실행 완료를 QuantService에 고지
- 3단계:
  - QuantService 기존 Task Scheduler/기존 실행 경로를 중지
  - 중지 전 최소 1회 이상 QuantOpsScheduler 백업 성공 확인 필요

## 5. 제약 및 주의사항

- 장중/장마감 등 시간 제약:
  - 시장 데이터 계산 작업은 Quant/QuantMarket 담당
  - QuantService 백업은 장중 제약 없음
  - 다만 배포/대량 git 작업 중에는 피하는 것이 좋음
- 휴장일 처리:
  - 백업은 휴장일에도 실행 가능
- 데이터 무결성 조건:
  - 백업 시점의 워킹트리 상태를 그대로 보존함
  - 미커밋 변경이 있어도 백업 대상에 포함됨
  - `.git`은 제외되므로 복구 시 Git metadata는 원격 repo 기준으로 복원해야 함
  - `git_head`는 참고 metadata일 뿐, zip 내부에는 `.git`이 없음
- 재실행 시 주의사항:
  - 같은 초 단위 timestamp 충돌 가능성은 낮지만, 중복 실행 금지
  - 실패 후 `_staging\QuantService_*` 잔여 폴더가 있으면 다음 실행 전 확인 필요
- 잠금 파일 또는 동시 실행 방지 장치:
  - 현재 명시적 lock file 없음
  - QuantOpsScheduler 이관 시 lock file 추가 권장:
    - `D:\QunatBackup\QuantService\.quantservice_backup.lock`
- 수동 확인이 필요한 케이스:
  - zip 크기 급감
  - `git_head=unknown`
  - 백업 루트 경로 오타
  - `D:\QunatBackup`와 `D:\QuantBackup` 혼용
  - `D:\QunatBackup`는 현재 사용자가 지정한 표준 경로이며, 철자 그대로 유지

## 6. 요청하는 통합 자동실행 결과

- 필요한 통합 결과 파일:
  - `D:\QuantOpsScheduler\state\shared-data\quantservice-backup-status.json`
  - `D:\QuantOpsScheduler\state\logs\quantservice-backup-monitor.log`
- 필요한 대시보드/요약:
  - 마지막 백업 시각
  - 최신 ZIP 경로/크기
  - `git_head`
  - 백업 age
  - 최근 성공/실패 상태
  - 보관 ZIP 개수
- 다른 쓰레드가 읽을 표준 파일명:
  - `latest_backup.txt`
  - `quantservice-backup-status.json`
- 알림이 필요한 실패 유형:
  - 백업 실패
  - 최신 백업 age 26시간 초과
  - zip 생성 후 파일 크기 1MB 미만
  - 최신 zip 경로 없음
  - staging 폴더 잔존
  - 2회 연속 실패
- 알림이 불필요한 정상 스킵 조건:
  - 같은 날 이미 정상 백업 완료되어 있고 수동 재실행 요청이 없는 경우
  - QuantService 폴더가 Git HEAD 동일 상태이고 정책상 1일 1회만 필요한 경우

## 7. 이관 완료 후 기존 작업 중지 요청

QuantOpsScheduler에서 다음을 완료한 뒤 QuantService 쓰레드에 고지해 주세요.

- QuantService 백업 자동실행 등록 완료
- `D:\QunatBackup\QuantService` 대상 백업 1회 이상 성공
- `latest_backup.txt`와 통합 상태 파일 생성 확인
- 실패 알림 정책 적용 확인

위 고지 확인 후 QuantService 쓰레드에서 기존 자동실행을 중지하겠습니다.

중지 대상:

- 기존 Task Scheduler에 등록된 QuantService 백업 작업
- 기존 `D:\QuantBackup\run_quantservice_backup.cmd` 기반 실행 경로

중지 전까지는 기존 자동실행을 유지합니다.

## 8. 참고: 자동실행 대상이 아닌 작업

아래 작업은 현재 QuantService에서 자동 반복 실행 대상으로 이관 요청하지 않습니다.

- Cloud Run 배포:
  - `D:\QuantService\deploy\cloud_run_deploy.ps1`
  - 수동 승인 후 실행 대상
- runtime snapshot 백업 스크립트:
  - `D:\QuantService\scripts\backup_runtime.ps1`
  - 폐지됨. QuantService 백업은 저장소 전체 백업 스크립트만 사용
- current JSON 생성:
  - Quant/QuantMarket 담당
  - QuantService는 웹 fallback/current 파일을 보관하거나 표시함
- git commit/push:
  - QuantOpsScheduler가 직접 수행하지 말 것
  - 필요 시 QuantService 쓰레드에 별도 작업요청서 발행

## 9. 2026-05-23 현재 확인값

- 현재 Git HEAD: `ac34445`
- 원격 동기화: `main...origin/main`
- 신규 백업 루트: `D:\QunatBackup\QuantService`
- 최신 백업:
  - `D:\QunatBackup\QuantService\QuantService_20260523_112130.zip`
  - `backup_created_at=2026-05-23 11:21:33 +09:00`
  - `git_head=ac34445`
- 과거 `D:\QuantBackup\QuantService_*.zip`: 신규 루트로 이동 완료
- 주의:
  - 2026-05-23 11:05 이후 `service_platform\web\public_data\market_analysis\current` JSON 파일들이 다시 수정 상태로 감지됨
  - 해당 current 데이터 변경은 새 백업 ZIP에 포함된 상태
