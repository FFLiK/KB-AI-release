# 실행과 운영

## 로컬 설치

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

PostgreSQL 드라이버가 필요한 경우:

```powershell
.venv\Scripts\python.exe -m pip install -e ".[dev,postgres]"
```

```env
RESEARCH_DATABASE_URL=postgresql+psycopg://user:password@host/database
DB_SCHEMA_MODE=validate
```


## 합성 데모 실행

합성 데모는 외부 API 키와 네트워크 호출 없이 선택한 데이터셋을 일반 분석 흐름으로 실행합니다. `backend/.env`에 다음 값을 설정한 뒤 서버를 다시 시작합니다.

```env
RESEARCH_PROVIDER_MODE=demo_replay
ENABLE_DEMO_DATASETS=1
DEMO_DATASET_ID=cafe-gangnam-festival.v1
DEMO_DATASET_ROOT=
API_AUTH_MODE=none
CORS_ALLOWED_ORIGINS=http://127.0.0.1:5173
```

현재 PowerShell 세션에 `RESEARCH_PROVIDER_MODE=fake` 또는 `real`이 이미 설정되어 있다면 변수를 제거하거나 `demo_replay`로 변경합니다. 프로세스 환경 변수는 `.env`보다 우선합니다.

백엔드와 프론트엔드를 일반 방식으로 시작한 뒤 화면이나 `POST /v1/analyses`에서 분석을 제출합니다. 원재료비 시나리오는 `DEMO_DATASET_ID=cafe-import-cost-shock.v1`로 변경하고 백엔드를 다시 시작합니다.

재생 검색 제공자, 문서 수집기와 추출기는 네트워크를 차단한 상태에서 데이터셋을 읽습니다. 선택된 조사 에이전트는 계속 실행되고, 생성된 후보는 표준 검증, 신호, 예측과 금융 계산 단계를 통과합니다.

배포 환경에서는 `ENABLE_DEMO_DATASETS=0`을 유지합니다. 데이터셋 구조, 검증 흐름과 운영상 제약은 [DEMO.md](DEMO.md)를 참고하세요.

## 데이터베이스

현재 Alembic head는 `0005_source_snapshot_fingerprint`입니다.

| 개정 | 내용 |
| --- | --- |
| `0001_research_schema` | 연구·출처·이벤트·정책·감사 테이블 |
| `0002_analysis_pipeline` | 공식 데이터 시점, 예측, 시나리오와 버전 결과 |
| `0003_analysis_jobs` | 비동기 작업 상태·오류와 결과 테넌트 필드 |
| `0004_policy_candidate_updated_at` | 정책 후보 갱신 시각 필드 추가 |
| `0005_source_snapshot_fingerprint` | 추출 관련 원문 스냅샷 식별자와 중복 제약 추가 |

마이그레이션:

```powershell
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe -m alembic current
.venv\Scripts\python.exe -m alembic check
```

운영 DB를 업그레이드하기 전에는 백업하고, 애플리케이션과 마이그레이션 코드를 같은 커밋으로 배포합니다.

SQLite 개발의 `DB_SCHEMA_MODE=auto`는 누락 테이블을 `create_all`로 만들 수 있으므로 Alembic 리비전 불일치를 숨길 수 있습니다. 배포·CI에서는 반드시 `alembic current`와 `alembic check`를 별도로 실행합니다.

## 서버 실행

```powershell
.venv\Scripts\python.exe -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
```

또는 패키지 설치 후:

```powershell
.venv\Scripts\kb-ai-api.exe
```

확인:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/ready
```

## 프론트엔드 두 프로세스 실행

백엔드를 `RESEARCH_PROVIDER_MODE=fake`, `API_AUTH_MODE=none`, `CORS_ALLOWED_ORIGINS=http://127.0.0.1:5173`으로 실행한 뒤 별도 터미널에서 다음을 실행합니다.

```powershell
cd frontend
npm ci
npm run dev
```

결정론적 브라우저 E2E는 `npm run test:e2e`, 실제 로컬 HTTP 경계 스모크는 `npm run test:e2e:real`입니다. 후자는 Playwright가 가짜 제공자 FastAPI(8010)와 Vite(5174)를 격리 기동하고 합성 카페의 주소 확인, 비동기 제출, 폴링, 결과 조회가 실제 HTTP 경계를 통과하는지 검사합니다. 두 경로 모두 외부 제공자 키를 요구하거나 출력하지 않습니다. 자세한 절차는 [TESTING.md](TESTING.md)를 참고하세요.

실제 외부 제공자 스모크는 `pytest -m live` 경계에서 별도로 실행합니다. 일반 프론트엔드 CI나 로컬 E2E에 포함하지 않습니다.

## 조사 시간 제한과 작업량 설정

조사 실행에는 고정된 60초 에이전트 제한이 없습니다. 기본값 `RESEARCH_AGENT_WALL_CLOCK_LIMIT_SECONDS=0`은 선택적인 에이전트 전체 제한을 비활성화합니다. 대신 작업별 시간 제한, 검색·문서·추출 작업량 상한, 제한된 재시도와 협력적 `ANALYSIS_JOB_TIMEOUT_SECONDS`로 안전성을 유지합니다.

로컬·CI 권장값:

```env
RESEARCH_SEARCH_REQUEST_TIMEOUT_SECONDS=30
RESEARCH_DOCUMENT_FETCH_TIMEOUT_SECONDS=15
RESEARCH_EXTRACTION_REQUEST_TIMEOUT_SECONDS=60
RESEARCH_AGENT_WALL_CLOCK_LIMIT_SECONDS=0
ANALYSIS_JOB_TIMEOUT_SECONDS=600
RESEARCH_MIN_DOCUMENTS_AFTER_DISCOVERY=3
RESEARCH_OFFICIAL_SEED_RESERVE=2
```

실제 제공자 연동 환경 예시:

```env
RESEARCH_SEARCH_REQUEST_TIMEOUT_SECONDS=90
RESEARCH_DOCUMENT_FETCH_TIMEOUT_SECONDS=30
RESEARCH_EXTRACTION_REQUEST_TIMEOUT_SECONDS=180
RESEARCH_AGENT_WALL_CLOCK_LIMIT_SECONDS=0
ANALYSIS_JOB_TIMEOUT_SECONDS=1800
RESEARCH_MIN_DOCUMENTS_AFTER_DISCOVERY=3
RESEARCH_OFFICIAL_SEED_RESERVE=2
```

이전 변수인 `GEMINI_TIMEOUT_SECONDS`, `OPENAI_TIMEOUT_SECONDS`, `RESEARCH_HTTP_TIMEOUT_SECONDS`도 대체값으로 지원합니다. 각 결과에는 비밀값이 아닌 실제 적용 제한, 단계별 소요 시간, 건너뛴 작업, 부분 결과 수와 작업별 시간 초과 사유 코드가 기록됩니다.

## 개발용 비동기 실행

`analysis_jobs`는 제출·실행·종료 상태와 구조화 오류를 데이터베이스에 저장합니다. 분석 결과, 섹션 결과, 공식 데이터 시점, 예측과 시나리오도 데이터베이스에 저장됩니다.

현재 작업 실행기는 `ThreadPoolExecutor` 기반 `in_process`입니다.

- 완료 결과와 오류 조회는 프로세스 재시작 후에도 가능합니다.
- 실행 중인 작업은 프로세스가 종료되면 이어서 처리되지 않습니다.
- `CeleryJobRunner`는 배포 확장 지점일 뿐 작업 등록과 제출 구현이 완료되지 않았습니다.
- `APP_ENV=production`에서 `in_process`를 사용하면 `/ready`가 실패합니다.

## 품질 검사

저장소에는 pytest·Vitest·Playwright 테스트 소스와 설정이 포함되어 있습니다. 실행 절차는 [TESTING.md](TESTING.md), 최근 검증 기록은 [TEST_RESULTS.md](TEST_RESULTS.md)를 참고하세요.

저장소 루트에서 백엔드 런타임과 계약을 검사하려면 다음을 실행합니다.

```powershell
cd backend
.\.venv\Scripts\python.exe -m compileall -q src scripts migrations
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m alembic check
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe scripts\export_schemas.py
cd ..
git diff --check
```

`backend/scripts/export_schemas.py`는 `backend/schemas/*.json`과 루트 `docs/openapi.json`을 현재 런타임 계약으로 갱신합니다. 생성 후 변경 사항을 검토하고 코드 변경과 같은 커밋에 포함합니다.

## 모니터링

- 요청마다 `X-Correlation-ID`를 수신하거나 생성합니다.
- `/internal/metrics`는 프로세스 내부 카운터·게이지와 p50/p95 분포를 반환합니다.
- 공식 제공자 지연·상태, 수집·승인·거절 수, 신선도와 누락 지표를 기록합니다.
- 검색·추출 토큰, 추정 비용, 검증 실패 코드, 이벤트 승인·거절 비율을 기록합니다.
- 시나리오 계산 지연과 결정론적 재생 불일치를 기록합니다.

여러 인스턴스 집계와 장기 보존에는 외부 지표·로그·추적 저장소가 필요합니다.

CI는 세 경로로 분리합니다.

- 기본 CI: 컴파일, `not live` pytest, 스키마·OpenAPI 불일치, 빈 데이터베이스 마이그레이션, `pip check`, 비밀정보 검사, `git diff --check`.
- 경로 기반 프론트엔드 CI: OpenAPI와 TypeScript 재생성 불일치, 타입 검사, 린트, 포맷, Vitest/MSW, 빌드, Chromium Playwright, UTF-8·자리표시자 검사.
- 예약·수동 라이브 CI: 공식 제공자, 지오코딩, Gemini/OpenAI, 작업량이 제한된 통합 캡처.

## 원문 보안과 보존

원문 수집기는 공개 HTTP(S) 주소만 허용하고, 리디렉션마다 사설·링크 로컬 목적지를 차단하며 크기·시간·MIME 타입을 제한합니다. HTML의 실행성 요소를 제거하고 프롬프트 인젝션 패턴을 기록합니다.

`RawSnapshotRetentionPolicy`는 보존 만료 여부와 스냅샷 루트 내부 경로인지 판단만 합니다. 실제 삭제는 감사 가능한 별도 운영 작업으로 구현해야 합니다.

운영에서는 다음이 추가로 필요합니다.

- 암호화된 객체 저장소와 백업
- 외부 통신 허용 목록
- 제공자 약관·저작권·로봇 배제 정책 검토
- 역할 기반 접근제어와 비밀정보 관리 서비스

## 보안 경계

- 신규 클라이언트는 인증 의존성이 적용된 복수형 `/v1/analyses/*` 경로를 사용합니다.
- 초기 단수형 호환 경로는 운영 ingress에서 차단하거나 코드에서 인증을 일원화해야 합니다.
- 현재 테넌트는 `default` 하나만 지원합니다.
- 검색 질의에는 신용점수, 대출잔액, 사업자번호를 포함하지 않습니다.
- 이 서비스는 정책 승인 또는 대출 실행을 수행하지 않습니다.

## 운영 배포 전 필수 작업

1. 깨끗한 Git 커밋에서 전체 검증과 스키마 생성을 완료합니다.
2. 실제 제공자 계약 테스트와 실패 시나리오를 통과시킵니다.
3. PostgreSQL과 외부 지속성 큐를 구성합니다.
4. 모든 공개 경로의 인증·권한·요청률 제한을 검증합니다.
5. 외부 지표·로그·추적 수집을 연결합니다.
6. 영향 계수와 정책 규칙을 사람 검토 후 활성화합니다.
7. 한국어 라벨 데이터로 추출·정책·요약 품질을 평가합니다.
8. 예측·정책 적격성·현금 고갈 분석이 의사결정 지원 정보라는 고지를 UI에 표시합니다.

## 자주 확인할 문제

### 공식 요청이 모두 `PARTIAL`인 경우

- API 키와 개별 서비스 활용 신청을 확인합니다.
- 요청 기간과 제공자 파라미터를 확인합니다.
- 실제 응답에 발표일을 매핑할 수 있는지 확인합니다.
- `provider_errors`에서 `MISSING_RELEASE_METADATA`, `NO_OBSERVATIONS` 등을 확인합니다.

### 로컬 DB가 head가 아닌 경우

```powershell
.venv\Scripts\python.exe -m alembic current
.venv\Scripts\python.exe -m alembic upgrade head
```

### 실제 검색 대신 fake 결과가 나오는 경우

`RESEARCH_PROVIDER_MODE=auto`는 Gemini와 OpenAI 키가 모두 없으면 `fake`로 전환됩니다. 실연동 검증 시 `real`을 명시해 누락 키가 알림 없이 대체 모드로 전환되지 않도록 합니다.

## 프론트엔드 구성과 품질 경계

프론트엔드는 React 19·엄격한 TypeScript·Vite로 구현합니다. 화면은 백엔드가 반환한 금액·비율·날짜를 표시하고 금융 값을 자체적으로 재계산하지 않습니다. 합성 카페 입력, 주소 확인, 비동기 분석 제출·폴링, 결과·근거·정책·What-if 비교, 반응형 테마를 제공합니다.

- 주소 확인은 `POST /v1/locations/geocode`를 통해 서버에서 수행합니다.
- 브라우저 번들에는 제공자 키·데이터베이스 자격 증명을 넣지 않으며, 금융 입력과 API 응답은 localStorage에 보관하지 않습니다. 테마와 최근 실행 ID만 저장합니다.
- 건너뛰기 링크, 명확한 키보드 초점, 오류 요약, `aria-live` 작업 상태, 색 외의 텍스트·아이콘 상태 표현과 차트 표 대안을 제공합니다.
- 모바일 메뉴와 상세 서랍은 Escape 키와 초점 복귀를 지원하며, `prefers-reduced-motion`에서는 애니메이션을 줄입니다.

프론트엔드 테스트 소스와 E2E 설정은 `frontend/`에 포함되어 있습니다. `npm run api:check`, `npm run typecheck`, `npm run lint`, `npm run format:check`, `npm test`, `npm run build`, `npm run test:e2e`, `npm run test:e2e:real`의 목적과 전제 조건은 [TESTING.md](TESTING.md)를 참고하세요.
