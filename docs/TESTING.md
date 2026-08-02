# 테스트 안내

이 저장소는 외부 제공자 호출 없이 재현 가능한 기본 회귀 테스트와, 별도 자격 증명이 필요한 실제 제공자 계약 테스트를 분리합니다. 기본 테스트는 가짜 제공자·로컬 고정 자료·임시 SQLite DB를 사용합니다.

## 사전 준비

백엔드는 Python 3.11 이상과 `backend/.venv`를 사용합니다. 프론트엔드는 `frontend/.nvmrc`의 Node.js 버전과 `npm ci`가 필요합니다. 브라우저 E2E를 처음 실행할 때는 Chromium을 설치합니다.

```powershell
cd frontend
npm ci
npx playwright install chromium
```

## 백엔드 회귀

```powershell
cd backend
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
$env:KB_AI_SKIP_DOTENV="1"
.\.venv\Scripts\python.exe -m pytest -m "not live" -q --tb=short -p no:cacheprovider
```

`not live` 범위는 입력·계약·공식 데이터 고정 자료·예측·금융 계산·분석 파이프라인을 검증합니다. `pytest -m live`는 실제 지도·공식 데이터·Gemini·OpenAI 계약을 호출할 수 있으므로, 필요한 키와 할당량를 명시적으로 준비한 경우에만 실행합니다.

## 프론트엔드 정적·단위 검증

```powershell
cd frontend
npm run typecheck
npm run lint
npm run format:check
npm run api:check
npm test
npm run build
```

- `api:check`은 `docs/openapi.json`과 `src/api/generated/schema.ts`의 불일치를 확인합니다.
- Vitest는 MSW를 사용해 API 응답을 모의하고 React 화면·상태·형식화·접근성 관련 동작을 검증합니다.
- `build`는 Vite 프로덕션 번들을 생성합니다.

## 브라우저 E2E

```powershell
cd frontend
npm run test:e2e
npm run test:e2e:real
```

`test:e2e`는 결정론적으로 API를 가로채 데스크톱·모바일 흐름과 접근성을 검증합니다. `test:e2e:real`은 다음 프로세스를 자동 기동합니다.

- 가짜 제공자 FastAPI 서버: `http://127.0.0.1:8010`
- Vite 개발 서버: `http://127.0.0.1:5174`

따라서 일반 개발 서버(8000/5173)와 충돌하지 않습니다. 기본적으로 `backend/.venv`의 Python을 사용하며, 다른 Python을 사용해야 한다면 `KB_AI_PYTHON` 환경 변수에 실행 파일 경로를 지정합니다. 실제 E2E는 외부 API 키를 요구하지 않습니다.

## 산출물과 기록

테스트가 만드는 `backend/data/test-runtime/`, `.test-tmp/`, `frontend/data/`, `frontend/test-results/`, `frontend/playwright-report*/`, `frontend/dist/`, `node_modules/`는 Git에서 제외합니다. 실행 결과는 이동하지 않고 [TEST_RESULTS.md](TEST_RESULTS.md)에 유지·갱신합니다.
