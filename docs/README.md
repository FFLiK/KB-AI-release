# 기술 문서 안내

이 디렉터리는 백엔드와 프론트엔드의 구조, 실행, 설정, 데모, 검증과 운영 경계를 설명합니다. 모든 설명은 현재 저장소 구조를 기준으로 하며, 필드·열거형·필수 조건은 생성된 `openapi.json`과 `backend/schemas/*.json`을 최종 기준으로 합니다.

## 문서 목록

| 문서 | 내용 |
| --- | --- |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 시스템 계층, 데이터 흐름, 모듈 책임과 보안 경계 |
| [API.md](API.md) | 프론트엔드와 외부 클라이언트가 사용하는 HTTP API 계약 |
| [CONFIGURATION.md](CONFIGURATION.md) | 백엔드 환경 변수, 외부 제공자, 데이터베이스와 인증 설정 |
| [OPERATIONS.md](OPERATIONS.md) | 백엔드·프론트엔드 설치와 실행, 마이그레이션, 운영 점검 |
| [DEMO.md](DEMO.md) | 합성 데모의 설정, 실행, 검증 흐름과 운영상 제약 |
| [TESTING.md](TESTING.md) | 백엔드·프론트엔드 테스트, 브라우저 E2E와 실제 제공자 테스트 경계 |
| [TEST_RESULTS.md](TEST_RESULTS.md) | 기록된 검증 결과와 확인 범위 |
| [openapi.json](openapi.json) | FastAPI 실행 코드에서 생성한 OpenAPI 계약 |

저장소 전체 소개와 파일 구조는 [루트 README](../README.md), 백엔드만 빠르게 실행하려면 [백엔드 README](../backend/README.md)를 참고하세요.

## 문서 갱신 원칙

- 백엔드 API나 Pydantic 계약을 변경하면 `backend`에서 `python scripts/export_schemas.py`를 실행해 `backend/schemas/*.json`과 `docs/openapi.json`을 갱신합니다.
- 프론트엔드는 `frontend`에서 `npm run api:generate`를 실행해 `src/api/generated/schema.ts`를 갱신합니다.
- 환경 변수, 마이그레이션, 실행 절차가 바뀌면 `CONFIGURATION.md`와 `OPERATIONS.md`를 함께 갱신합니다.
- 데모 데이터셋이나 검증 흐름을 바꾸면 루트 README와 `DEMO.md`를 함께 갱신합니다.
- 검증 결과 문서에는 실제 실행한 결과만 `TEST_RESULTS.md`에 기록합니다. 합성·기록 재생 결과를 실제 외부 제공자 성공으로 표현하지 않습니다.

## 생성 파일과 직접 편집 파일

- 직접 편집: 이 디렉터리의 Markdown 문서
- 자동 생성: `openapi.json`, `backend/schemas/*.json`, `frontend/src/api/generated/schema.ts`

생성 파일은 직접 수정하지 않고 생성 명령을 실행한 뒤 변경 내용을 검토해 코드와 같은 커밋에 포함합니다.
