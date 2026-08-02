# KB AI 소상공인 현금흐름 분석

KB AI는 소상공인의 매출·비용·대출·현금흐름 입력과 공식 통계, 검증된 지역·업종·정책 정보를 결합해 월별 현금흐름과 손익분기점(BEP)을 분석하는 FastAPI + React 기반 MVP입니다. 외부 AI와 데이터 제공자는 자료 탐색과 구조화에만 사용하며, 금융 수치 계산과 결과 버전 관리는 결정론적 백엔드 코드가 수행합니다.

이 저장소에는 실행 코드, 환경 변수 예시, 데이터베이스 마이그레이션, 생성된 API 계약, 합성 데모 2종, 기술 문서와 백엔드·프론트엔드 테스트가 포함되어 있습니다.

## 핵심 원칙

- 검증된 정보만 재무 신호로 변환합니다.
- 출처·근거·날짜·위치·업종 검증에 실패한 후보는 금융 계산에 반영하지 않습니다.
- 기준 예측, 공식 데이터 반영, AI 조사 반영 결과를 단계별로 분리합니다.
- 정책 후보의 신청 자격·기간·예산 상태를 확인하지 못하면 추천하지 않고 `추가 확인 필요`로 표시합니다.
- 합성 데모와 실제 조사 결과를 화면과 데이터 계약에서 명확히 구분합니다.

## 실행 환경

- Python 3.11 이상
- Node.js: `frontend/.nvmrc`에 지정된 버전
- Windows PowerShell 기준 실행 예시
- 외부 API 키 없이 실행 가능한 `fake` 및 `demo_replay` 모드

## 빠른 시작

### 백엔드

저장소 루트에서 다음을 실행합니다.

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m alembic upgrade head
$env:API_AUTH_MODE="none"
$env:CORS_ALLOWED_ORIGINS="http://127.0.0.1:5173"
.\.venv\Scripts\python.exe -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
```

`http://127.0.0.1:8000/health`에서 상태를 확인합니다. 실제 외부 제공자를 사용하려면 `backend/.env`에 자격 증명을 설정하고 [설정 문서](docs/CONFIGURATION.md)의 제공자 모드를 따릅니다.

PowerShell 프로세스 환경 변수는 `.env`보다 우선합니다. 이전 세션에 `RESEARCH_PROVIDER_MODE`가 설정되어 있다면 `.env`와 충돌하지 않는지 확인한 뒤 백엔드를 다시 시작해야 합니다.

### 프론트엔드

백엔드를 실행한 상태에서 별도 터미널을 엽니다.

```powershell
cd frontend
npm ci
npm run dev
```

브라우저에서 `http://127.0.0.1:5173`을 엽니다. API 주소를 변경할 때만 `frontend/.env.example`을 `.env`로 복사해 `VITE_API_BASE_URL`을 설정합니다. 제공자 키나 데이터베이스 자격 증명은 `VITE_*` 변수에 넣지 않습니다.

## 합성 데모

두 데모는 외부 네트워크와 AI 모델 호출 없이 일반 분석 파이프라인을 재현합니다. 합성 자료가 검색·원문·추출 제공자를 대신하지만, 이벤트 검증, 신호 생성, 예측과 금융 계산은 실제 실행과 같은 코드 경로를 사용합니다.

| 데이터셋 | 시나리오 | 재무 축 |
| --- | --- | --- |
| `cafe-gangnam-festival.v1` | 점포 인근 강남 커피거리 축제와 방문 수요 증가 | `REVENUE_DEMAND` 증가 |
| `cafe-import-cost-shock.v1` | 2026년 7~12월 원두 공급 차질과 원재료비 증가 | `INGREDIENT_COST` 증가 |

`backend/.env`에 다음 값을 설정한 뒤 백엔드를 다시 시작합니다.

```env
RESEARCH_PROVIDER_MODE=demo_replay
ENABLE_DEMO_DATASETS=1
DEMO_DATASET_ID=cafe-gangnam-festival.v1
DEMO_DATASET_ROOT=
```

원재료비 시나리오는 `DEMO_DATASET_ID=cafe-import-cost-shock.v1`로 변경합니다. 데모의 구성, 검증 흐름과 제약 사항은 [합성 데모 안내](docs/DEMO.md)를 참고하세요.

## 저장소 구조

```text
.
├─ backend/                         # FastAPI 백엔드와 분석 파이프라인
│  ├─ src/
│  │  ├─ api/                       # HTTP 엔드포인트와 인증 경계
│  │  ├─ contracts/                 # Pydantic 입력·결과·근거 계약
│  │  ├─ ingestion/                 # 사용자 입력과 공식 데이터 수집
│  │  ├─ research_agents/           # 거시·업종·지역·정책 조사 에이전트
│  │  ├─ providers/                 # 검색·문서·추출·데모 제공자
│  │  ├─ validation/                # 증거·날짜·위치·정책 검증
│  │  ├─ signals/                   # 검증 이벤트의 점포 신호 변환
│  │  ├─ forecasting/               # 내부 추세와 공식 지표 예측
│  │  ├─ finance/                   # 현금흐름·대출·BEP 계산
│  │  ├─ relief/                    # 지원 정책 적격성·효과 계산
│  │  ├─ storage/                   # SQLAlchemy 저장소와 스키마
│  │  └─ orchestration/             # 비동기 분석 실행과 상태 관리
│  ├─ migrations/                   # Alembic 데이터베이스 변경 이력
│  ├─ schemas/                      # 생성된 JSON Schema
│  ├─ scripts/                      # 계약 생성과 품질 검사 도구
│  ├─ tests/                        # 계약·회귀·E2E·라이브 테스트
│  ├─ .env.example                  # 백엔드 환경 변수 예시
│  └─ README.md                     # 백엔드 빠른 안내
├─ frontend/                        # React·TypeScript 사용자 화면
│  ├─ src/                          # 화면, API 클라이언트, 단위·통합 테스트
│  ├─ e2e/                          # 결정론적 Playwright 시나리오
│  ├─ e2e-real/                     # 로컬 FastAPI 연동 스모크 테스트
│  ├─ .env.example                  # 공개 가능한 프론트엔드 설정 예시
│  └─ THIRD_PARTY_NOTICES.md        # 제3자 고지
├─ demo/
│  ├─ datasets/                     # 합성 데모 데이터셋 2종
│  └─ index.json                    # 데모 데이터셋 카탈로그
├─ docs/
│  ├─ README.md                     # 문서 색인
│  ├─ ARCHITECTURE.md               # 시스템 구조와 책임 경계
│  ├─ API.md                        # HTTP API 사용 안내
│  ├─ CONFIGURATION.md              # 환경 변수와 제공자 설정
│  ├─ OPERATIONS.md                 # 설치·실행·운영 점검
│  ├─ DEMO.md                       # 합성 데모 실행과 검증 안내
│  ├─ TESTING.md                    # 테스트 실행과 격리 원칙
│  ├─ TEST_RESULTS.md               # 검증 결과
│  └─ openapi.json                  # 생성된 OpenAPI 계약
├─ .gitattributes
├─ .gitignore
└─ README.md
```

## 문서 안내

- [문서 전체 색인](docs/README.md)
- [시스템 아키텍처](docs/ARCHITECTURE.md): 처리 계층, 데이터 흐름, 책임·보안 경계
- [HTTP API 명세](docs/API.md): 분석 제출·조회, 주소 확인, 근거와 오류 계약
- [설정과 외부 제공자](docs/CONFIGURATION.md): 환경 변수, 제공자 모드, 공식 데이터와 인증
- [실행과 운영](docs/OPERATIONS.md): 설치, 마이그레이션, 서버 실행과 배포 전 점검
- [합성 데모 안내](docs/DEMO.md): 데이터셋 선택, 검증 흐름과 운영상 제약
- [테스트 안내](docs/TESTING.md): 백엔드·프론트엔드·브라우저·라이브 테스트 경계
- [검증 결과](docs/TEST_RESULTS.md): 기록된 테스트 결과와 검증 범위

`backend/schemas/*.json`, `docs/openapi.json`, `frontend/src/api/generated/schema.ts`는 생성된 계약입니다. 직접 수정하지 말고 백엔드에서 `python scripts/export_schemas.py`, 프론트엔드에서 `npm run api:generate`로 다시 생성합니다.

## 처리 구조

```text
사용자 입력·CSV
      │
      ▼
프론트엔드(React) ── HTTP ──► 백엔드 API(FastAPI)
                                      │
                 ┌────────────────────┼────────────────────┐
                 ▼                    ▼                    ▼
          입력·주소 검증       공식 데이터·조사 수집     비동기 분석 작업
                 │                    │                    │
                 └──────────────► 결정론적 예측·금융 계산 ◄─┘
                                      │
                                      ▼
                         SQLite/PostgreSQL 결과·근거·버전 저장
                                      │
                                      ▼
                           결과·근거·정책·What-if 화면
```

브라우저는 서버 결과를 표시하고 금융 값을 재계산하지 않습니다. 검증에 실패한 조사 후보는 근거와 제외 사유를 남기되 금융 신호로 반영하지 않습니다.

## 테스트

상세 절차는 [테스트 안내](docs/TESTING.md), 최신 수치는 [검증 결과](docs/TEST_RESULTS.md)를 참고하세요.

### 백엔드

```powershell
cd backend
$env:KB_AI_SKIP_DOTENV="1"
.\.venv\Scripts\python.exe -m pytest -m "not live" -q --tb=short -p no:cacheprovider
```

### 프론트엔드

```powershell
cd frontend
npm run typecheck
npm run lint
npm run format:check
npm run api:check
npm test
npm run build
npm run test:e2e
npm run test:e2e:real
```

`test:e2e`는 결정론적 브라우저 흐름을 검증합니다. `test:e2e:real`은 외부 API 없이 로컬 FastAPI와 Vite 사이의 실제 HTTP 경계를 검증합니다. 실제 외부 제공자 호출은 필요한 자격 증명과 비용을 확인한 뒤 `pytest -m live`로 별도 실행합니다.
