# 검증 결과

기준 기록: **2026-08-03 (Asia/Seoul)**

이 문서는 기준 기록일의 코드에서 직접 실행한 검증만 기록합니다. 저장된 고정 자료나 합성 제공자 결과를 실제 외부 제공자 호출 성공으로 해석하지 않습니다.

## 검증 요약

| 범위 | 실행 명령 또는 방법 | 결과 |
| --- | --- | --- |
| 백엔드 비라이브 회귀 | `.\.venv\Scripts\python.exe -m pytest -m "not live" -q --tb=short -p no:cacheprovider` | **335개 통과, `live` 13개 제외** |
| 정책·BOK·오래된 자료 안정화 회귀 | 전체 백엔드 테스트 모음에 포함 | 통과 |
| Python 컴파일 | `.\.venv\Scripts\python.exe -m compileall -q src scripts migrations tests` | 통과 |
| Python 의존성 | `.\.venv\Scripts\python.exe -m pip check` | 통과 |
| 빈 데이터베이스 마이그레이션 | `alembic upgrade head`, `alembic current`, `alembic check` | **0005 head**, 불일치 없음 |
| JSON Schema·OpenAPI·TypeScript 계약 | `scripts/export_schemas.py`, `npm run api:check` | 불일치 없음 |
| 프론트엔드 타입·린트·포맷·빌드 | `npm run typecheck`, `npm run lint`, `npm run format:check`, `npm run build` | 통과 |
| 프론트엔드 단위·통합 | `npm test` | **8개 파일, 42개 테스트 통과** |
| 결정론적 Chromium E2E | `npm run test:e2e` | **4개 통과** |
| 실제 로컬 HTTP E2E | `npm run test:e2e:real` | **1개 통과** |
| 인코딩·자리표시자·비밀정보·차이 | 검사 스크립트와 `git diff --check` | 통과 |

백엔드 테스트 모음에는 기능에 영향을 주지 않는 Starlette/httpx 지원 중단 예정 경고 1건이 있었습니다. 실패나 제외로 처리되지 않았습니다.

## 확인한 핵심 동작

- 신뢰할 수 있는 BOK 문서에서 정책 결정 수치를 선택하고, 다른 전망 수치가 기준금리로 오인되지 않도록 검증합니다.
- 같은 지원 정책을 서로 다른 출처에서 발견해도 의미상 동일하면 병합하며, 핵심 조건이 충돌하면 자동 추천 대신 검토 대상으로 남깁니다.
- 오래되었거나 종료된 자료, 탐색용 목록, 본문이 빈약한 문서는 금융 신호나 현재 지원 정책으로 승격하지 않습니다.
- 이벤트·정책 추출 ID는 실행, 에이전트, 출처 개정 식별자와 로컬 순번을 포함해 충돌 없이 재현됩니다.
- 후보, 검증 결과, 참고 전용 자료, 적용 신호의 처리 단계와 단계별 집계를 API와 UI에서 구분합니다.
- 결정론적 합성 데모는 일반 검증·신호·예측·금융 경로를 통과하며 화면에서 실제 라이브 근거가 아님을 명시합니다.
- 실제 로컬 HTTP E2E는 브라우저, Vite, FastAPI, 비동기 제출·폴링·결과 조회 경계를 연결해 확인합니다.

## 검증 경계

| 구분 | 의미 |
| --- | --- |
| 결정론적·오프라인 | 자격 증명을 제거한 고정 자료·모의 응답·합성 재생 기반 검증 |
| 실제 로컬 HTTP | 외부 API 없이 가짜 제공자 FastAPI와 Vite 사이의 실제 HTTP 경계 검증 |
| 실제 제공자 | Gemini, OpenAI, Kakao, KOSIS 등 외부 서비스에 실제 요청을 보내는 별도 `live` 표식 검증 |
| 참고 전용 | 화면에는 근거로 표시할 수 있지만 금융 신호나 정책 추천에는 반영하지 않는 자료 |

기준 기록일에는 외부 제공자 자격 증명을 사용하는 `pytest -m live`를 실행하지 않았습니다. 따라서 외부 검색 결과, API 할당량과 제공자 응답 형식은 이 기록의 검증 범위에 포함되지 않습니다. 네트워크와 자격 증명 없이 재현할 때는 `demo_replay`를 사용할 수 있습니다.

## 남아 있는 MVP 한계

- 실제 제공자의 응답, 검색 순위, 할당량과 지연은 비결정적이며 모든 공식 문서가 유효 이벤트나 정책으로 변환되는 것은 아닙니다.
- 정책 적격성, 예산 잔여 여부와 최종 승인은 반드시 공식 기관에서 다시 확인해야 합니다.
- SQLite, 프로세스 내부 작업 실행기와 프로세스 내부 지표는 단일 인스턴스 MVP 경계이며 운영 확장 구성은 아닙니다.
- 이벤트 계수는 검증된 인과 추정치가 아니라 근거가 표시된 스트레스 가정일 수 있습니다.

실행 방법은 [OPERATIONS.md](OPERATIONS.md), 테스트 격리와 라이브 경계는 [TESTING.md](TESTING.md), 합성 데모 절차는 [DEMO.md](DEMO.md)를 참고하세요.
