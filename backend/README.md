# KB AI 소상공인 현금흐름 분석 백엔드

이 디렉터리는 FastAPI API, Pydantic 계약, 분석 오케스트레이션, 공식 데이터·조사 제공자, 검증, 예측·금융 계산, 정책 분석, SQLAlchemy 저장소, Alembic 마이그레이션과 생성 스키마를 포함합니다.

## 주요 구조

```text
backend/
├─ src/                 # API, 계약, 수집, 검증, 신호, 예측, 금융·정책 계산
├─ migrations/          # Alembic 마이그레이션
├─ schemas/             # 생성된 JSON Schema
├─ scripts/             # 계약 생성, 인코딩·비밀정보 검사와 재현 도구
├─ tests/               # 계약·회귀·E2E·라이브 테스트
├─ .env.example         # 환경 변수 예시
├─ alembic.ini
├─ pyproject.toml
└─ requirements.txt
```

## 설치

저장소 루트에서 실행합니다.

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m alembic upgrade head
```

## 실행

외부 API 키가 필요 없는 기본 개발 모드:

```powershell
cd backend
$env:RESEARCH_PROVIDER_MODE="fake"
$env:API_AUTH_MODE="none"
.\.venv\Scripts\python.exe -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
```

상태 확인:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

합성 데모는 `backend/.env`에서 `RESEARCH_PROVIDER_MODE=demo_replay`, `ENABLE_DEMO_DATASETS=1`, `DEMO_DATASET_ID`를 설정한 뒤 서버를 다시 시작합니다. 자세한 내용은 [합성 데모 안내](../docs/DEMO.md)를 참고하세요.

## 테스트

```powershell
$env:KB_AI_SKIP_DOTENV="1"
.\.venv\Scripts\python.exe -m pytest -m "not live" -q --tb=short -p no:cacheprovider
```

저장소에는 전체 백엔드 테스트 소스가 포함되어 있습니다. 실제 제공자 호출이 필요한 테스트는 `live` 표식으로 분리되어 있으며 명시적으로 자격 증명을 준비한 경우에만 실행합니다.

전체 사용 방법은 [루트 README](../README.md), 설정·API·운영·검증 문서는 [기술 문서 색인](../docs/README.md)을 참고하세요.
