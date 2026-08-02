# 설정과 외부 제공자

## 설정 원칙

저장소 루트에서 `cd backend`로 이동한 뒤 예제 파일을 복사해 백엔드 로컬 설정을 만듭니다.

```powershell
Copy-Item .env.example .env
```

`.env`는 Git에 커밋하지 않습니다. 운영 환경에서는 파일 대신 비밀정보 관리 서비스나 배포 환경변수를 사용합니다. 브라우저에 노출되는 `VITE_*` 변수에는 API 기본 주소처럼 공개 가능한 값만 넣어야 하며, LLM·지도·공식 데이터 제공자 키, 데이터베이스 URL, `API_AUTH_KEY`를 넣으면 안 됩니다.

## 외부 키 없는 권장 시작 모드

처음 개발하거나 결정론적 데모를 실행할 때는 다음 설정을 사용합니다.

```env
APP_ENV=development
RESEARCH_PROVIDER_MODE=fake
RESEARCH_DATABASE_URL=sqlite:///./data/research.db
DB_SCHEMA_MODE=auto
JOB_RUNNER_MODE=in_process
API_AUTH_MODE=none
TENANT_MODE=single
```

`fake` 모드는 고정 자료 기반 검색·추출·주소 확인을 사용합니다. 실제 뉴스·공고·정책·공식 지표를 자동으로 제공한다는 뜻이 아닙니다. 등록된 합성 주소만 결정론적으로 지오코딩하며, 그 밖의 주소는 좌표를 추정하지 않고 실패 폐쇄합니다.


## 합성 데모 재생

`demo_replay`는 선택한 합성 데이터셋을 사용하는 오프라인 조사 제공자 모드입니다. 외부 검색, 문서 수집과 이벤트 추출을 통제된 재생 데이터로 대체하지만, 일반 조사 에이전트와 검증, 신호 생성, 예측과 금융 계산 단계는 그대로 실행합니다.

```env
RESEARCH_PROVIDER_MODE=demo_replay
ENABLE_DEMO_DATASETS=1
DEMO_DATASET_ID=cafe-gangnam-festival.v1
# 비워 두면 저장소의 demo/ 디렉터리를 사용합니다.
DEMO_DATASET_ROOT=
```

| 변수 | 필수 여부 | 용도 |
| --- | --- | --- |
| `RESEARCH_PROVIDER_MODE` | 필수 | 합성 재생 제공자를 사용하려면 `demo_replay`로 설정 |
| `ENABLE_DEMO_DATASETS` | 필수 | `1`과 같은 참 값으로 설정 |
| `DEMO_DATASET_ID` | 필수 | 재생할 시나리오의 카탈로그 ID |
| `DEMO_DATASET_ROOT` | 선택 | 카탈로그와 데이터셋이 있는 절대 경로이며 기본값은 저장소의 `demo/` |

재생 모드는 네트워크를 사용하지 않고 `SYNTHETIC_DEMO_ONLY` 데이터셋만 허용합니다. 외부 AI 모델을 호출하거나 재무 신호를 직접 주입하지 않으며, 후보와 근거가 표준 검증·신호 게이트를 통과해야 재무에 적용됩니다. 자세한 내용은 [DEMO.md](DEMO.md)를 참고하세요.

## 조사 제공자 모드

| 값 | 검색 | 이벤트·정책 추출 | 필요 조건 |
| --- | --- | --- | --- |
| `fake` | 오프라인 고정 응답 | 오프라인 고정 응답 | 없음 |
| `demo_replay` | 선택한 합성 검색 재생 | 선택한 합성 문서·후보 재생 | `ENABLE_DEMO_DATASETS=1`, `DEMO_DATASET_ID` |
| `auto` | 필수 키가 있으면 실제 제공자, 없으면 `fake` | 검색 모드와 동일 | 선택 |
| `real` | Gemini 검색 근거화 | OpenAI 구조화 추출 | Gemini·OpenAI 키 |
| `local` | Gemini 검색 근거화 | OpenAI 호환 로컬 엔드포인트와 OpenAI 정책 추출 | 키와 로컬 엔드포인트 |

명시적인 `real`/`local` 모드에 필수 키가 없으면 시작 시 실패합니다. 실연동을 확인할 때는 `auto` 대신 `real`을 명시해 알림 없는 `fake` 대체 동작을 피합니다.

```env
RESEARCH_PROVIDER_MODE=real
GEMINI_API_KEY=
GEMINI_SEARCH_MODEL=gemini-3.6-flash
OPENAI_API_KEY=
OPENAI_EXTRACTION_MODEL=gpt-5.6-terra
```

모델명은 예시 기본값입니다. 실제 배포 전에는 해당 계정에서 사용 가능한 모델인지 제공자 문서와 호출 결과로 확인해야 합니다.

## 공식 데이터와 지도 API

| 우선순위 | 변수 | 용도 | 발급처 |
| ---: | --- | --- | --- |
| 1 | `KAKAO_REST_API_KEY` | 주소 지오코딩 | [Kakao Developers](https://developers.kakao.com/) |
| 2 | `ECOS_API_KEY` | 금리·환율 등 | [한국은행 ECOS](https://ecos.bok.or.kr/api/) |
| 3 | `KOSIS_API_KEY` | 물가·소비·업종·지역 통계 | [KOSIS 공유서비스](https://kosis.kr/openapi/) |
| 4 | `DATA_GO_KR_API_KEY` | 공공데이터포털 공통 키 | [공공데이터포털](https://www.data.go.kr/) |
| 4 | `CUSTOMS_API_KEY` | 관세청 전용 키 | 공공데이터포털 |
| 4 | `PUBLIC_DATA_API_KEY` | 상권·점포 참조 데이터 전용 키 | 공공데이터포털 |
| 대체 | `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` | Kakao 실패 시 보조 지오코딩 | Naver Cloud |

공공데이터포털은 키 발급과 별도로 개별 서비스의 활용 신청이 필요할 수 있습니다. 키를 입력했다고 실연동 검증이 끝난 것은 아닙니다. 제공자별로 관측일·발표일 의미, `released_at`/`available_at` 매핑, 개정 식별자, 단위·주기, 오류·할당량 응답을 확인해야 합니다. 발표 메타데이터를 신뢰할 수 없는 공식 관측값은 저장될 수 있어도 계산 특성값에는 사용하지 않습니다.

```env
ECOS_API_KEY=
KOSIS_API_KEY=
DATA_GO_KR_API_KEY=
CUSTOMS_API_KEY=
PUBLIC_DATA_API_KEY=
KAKAO_REST_API_KEY=
NAVER_CLIENT_ID=
NAVER_CLIENT_SECRET=
```

## 저장소와 작업 실행

| 변수 | 기본값 | 현재 의미 |
| --- | --- | --- |
| `RESEARCH_DATABASE_URL` | `sqlite:///./data/research.db` | SQLAlchemy 연결 URL |
| `DB_SCHEMA_MODE` | `auto` | SQLite는 `create_all`, PostgreSQL은 스키마 검증 |
| `SOURCE_SNAPSHOT_DIR` | `./data/source_snapshots` | 원문 스냅샷 저장 위치 |
| `JOB_RUNNER_MODE` | `in_process` | 현 MVP에서 실제 사용 가능한 실행기 |
| `TENANT_MODE` | `single` | 현재 지원하는 테넌트 경계 |
| `RESULT_RETENTION_DAYS` | `365` | 예약된 결과 보존 값, 자동 삭제 미연결 |
| `RAW_SNAPSHOT_RETENTION_DAYS` | `90` | 예약된 원문 보존 값, 자동 삭제 미연결 |

`OFFICIAL_DATA_PROVIDER_MODE`, `REDIS_URL`, 보존 기간 설정은 설정 객체에 있을 수 있으나, 제공자 선택·외부 큐·자동 삭제 작업까지 완전히 연결된 운영 기능으로 보면 안 됩니다.

## HTTP·CORS·인증

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `API_HOST` | `127.0.0.1` | CLI 실행 호스트 |
| `API_PORT` | `8000` | CLI 실행 포트 |
| `CORS_ALLOWED_ORIGINS` | 빈 값 | 쉼표 구분 허용 출처 |
| `API_AUTH_MODE` | `none` | `none` 또는 `api_key` |
| `API_AUTH_KEY` | 빈 값 | `X-API-Key` 비교 값 |
| `RATE_LIMIT_PER_MINUTE` | `0` | 0이면 비활성, 프로세스 내 IP 기준 |

Vite 개발 서버와 연결할 때는 다음을 사용합니다.

```env
CORS_ALLOWED_ORIGINS=http://127.0.0.1:5173,http://localhost:5173
VITE_API_BASE_URL=http://127.0.0.1:8000
```

운영 설정의 최소 예시는 다음과 같지만, 현재 `in_process` 실행기만으로는 `/ready`가 성공하지 않습니다. 지속성 작업 실행기, 인증 일원화, 외부 관측성을 함께 갖춰야 합니다.

```env
APP_ENV=production
API_AUTH_MODE=api_key
API_AUTH_KEY=<secret>
RATE_LIMIT_PER_MINUTE=60
TENANT_MODE=single
```

## 모델 호출과 원문 안전 제어

```env
OPENAI_TIMEOUT_SECONDS=90
OPENAI_MAX_OUTPUT_TOKENS=6000
RESEARCH_HTTP_TIMEOUT_SECONDS=15
RESEARCH_MAX_DOCUMENT_BYTES=5242880
RESEARCH_MAX_REDIRECTS=3
RESEARCH_MAX_SEARCH_RETRIES=1
RESEARCH_MAX_EXTRACTION_RETRIES=1
FORECAST_MIN_IMPROVEMENT=0
FORECAST_BACKTEST_WINDOWS=12
```

검색·추출 재시도는 제한되어 있습니다. 정책 HTTP 400, 스키마 오류, 거절 응답은 재시도하지 않습니다. 시간 초과, 408, 409, 429, 5xx 응답에만 설정된 한 번의 재시도를 적용할 수 있습니다. `incomplete/max_output_tokens`는 출력 예산을 두 배로 늘려 한 번 재시도할 수 있습니다. 제공자 메시지와 응답 본문은 저장하지 않습니다.

추출 품질 게이트는 모델 입력을 30,000자로 제한하고 잘림 여부를 기록합니다. 유료 모델 호출 전 탐색용 목록·내비게이션 페이지, 오래된 문서, 무관한 문서, 빈 문서, 너무 짧은 원문을 제외합니다.

토큰 단가 변수의 기본값 0은 무료라는 뜻이 아니라 설정되지 않았다는 표시입니다. 해당 모델의 단가가 모두 0이면 호출 기록은 `estimated_cost=null`, `cost_status=RATE_NOT_CONFIGURED`로 남습니다. 비용이 0이라고 해석하면 안 됩니다.

## 테스트 격리와 실제 제공자 명시적 실행

기본 테스트는 외부 자격 증명을 제거하고 소켓 연결을 차단합니다. 실제 제공자 검증은 `live` 표식으로만 실행합니다.

```powershell
.venv\Scripts\python.exe -m pytest -m "not live" -q -p no:cacheprovider
.venv\Scripts\python.exe -m pytest -m live -q -rs -p no:cacheprovider
```

`live` 테스트에서 자격 증명이 없으면 명시적인 제외로 기록됩니다. 자격 증명이 설정된 뒤 발생한 인증·할당량·형식 오류는 성공이나 제외가 아니라 실패입니다. 자세한 실행 근거는 [TEST_RESULTS.md](TEST_RESULTS.md)를 참고하세요.
