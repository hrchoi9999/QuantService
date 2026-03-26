# QS 쓰레드 WORKLOG 템플릿

이 문서는 각 쓰레드의 `WORKLOG.md`를 같은 형식으로 기록하기 위한 표준 템플릿입니다.

권장 원칙:

- 큰 작업이 끝날 때마다 1건씩 추가합니다.
- 장문 설명보다 “무엇을 했고, 무엇이 남았는지”가 바로 보이게 짧게 씁니다.
- 커밋, 검증, 배포 여부를 최소 단위로 남깁니다.

## 권장 기록 형식

```md
# <쓰레드명> Worklog

## YYYY-MM-DD

### 작업명

- 요청 출처:
- 목적:
- 반영 범위:
  - 
  - 
- 주요 변경:
  - 
  - 
- 검증:
  - `pytest ...`
  - `ruff check ...`
  - `black --check ...`
- 커밋:
  - `<hash> <message>`
- 배포:
  - 미배포 / 배포 완료
- 메모:
  - 
```

## 더 짧은 실무형 예시

```md
## 2026-03-26

### 시장 브리핑 공개 고도화 1차

- 요청 출처: QuantMarket
- 반영 범위: 홈 / 시장 브리핑 / 오늘
- 주요 변경:
  - 상태 타임라인 추가
  - 자산군 상대강도 추가
  - 상태 전이 요약 추가
- 검증:
  - `pytest tests\\test_web -q`
  - `ruff check service_platform tests`
  - `black --check`
- 커밋:
  - `72b0173 feat: enhance public market briefing pages`
- 배포:
  - Cloud Run 배포 완료
```

## 기록 시 주의사항

- 쓰레드 범위를 벗어나는 내용은 길게 쓰지 말고 `QS-Master` 또는 다른 쓰레드 문서로 넘깁니다.
- 외부 후속 요청이 생기면 `BACKLOG.md`에도 함께 남깁니다.
- 공개 반영 작업이면 배포 여부를 반드시 적습니다.
