# HTTP API 명세

## 표준 계약과 인증

FastAPI 애플리케이션은 `backend/src/api/main.py`에 있습니다. 표준 결과 계약은 `analysis_result.v1` 스키마의 `AnalysisResultV1`이며, 전체 필드·열거형·필수 조건은 생성된 [openapi.json](openapi.json)을 최종 기준으로 합니다.

```text
http://127.0.0.1:8000
```

`API_AUTH_MODE=api_key`에서 보호된 경로를 호출할 때는 다음 헤더가 필요합니다.

```http
X-API-Key: <API_AUTH_KEY>
```

신규 클라이언트는 아래 복수형 `/v1/analyses` 경로를 사용해야 합니다. 단수형 초기 연구 API는 내부 호환 용도이며 운영 노출 대상이 아닙니다.

## 표준 엔드포인트

| 메서드 | 경로 | 용도 |
| --- | --- | --- |
| `POST` | `/v1/analyses` | 비동기 분석 제출 |
| `POST` | `/v1/analyses/sync` | 동일 오케스트레이터 동기 실행 |
| `GET` | `/v1/analyses/{run_id}` | 저장된 작업 상태·오류 조회 |
| `GET` | `/v1/analyses/{run_id}/result` | 최신 또는 지정 버전 결과 조회 |
| `POST` | `/v1/analyses/{run_id}/what-if` | 파생 시나리오와 새 결과 버전 생성 |
| `POST` | `/v1/inputs/csv/validate` | 파싱된 CSV 행 검증 |
| `POST` | `/v1/locations/geocode` | 서버 측 주소 확인 |
| `GET` | `/v1/events/{event_id}/evidence` | 확정 이벤트의 인용·출처 개정 식별자 조회 |
| `GET` | `/v1/event-candidates/{candidate_id}/evidence` | 거절 후보의 검증·인용 근거 조회 |
| `GET` | `/v1/policies/{policy_id}` | 정책 후보와 공식 근거 조회 |
| `GET` | `/internal/metrics` | 프로세스 내 카운터·지연시간 조회 |
| `GET` | `/health` | 프로세스 생존 상태 |
| `GET` | `/ready` | DB·작업 실행기·운영 경계 준비 상태 |

`GET /v1/analyses/{run_id}/result?version=2`처럼 `version` 쿼리로 과거 결과 버전을 지정할 수 있습니다.

## 분석 요청

```json
{
  "store_profile": {
    "store_id": "STORE-001",
    "business_type_code": "FNB_CAFE",
    "address": "서울특별시 강남구 테헤란로 123",
    "latitude": 37.4979,
    "longitude": 127.0276,
    "forecast_horizon_months": 2,
    "minimum_operating_cash_krw": 5000000,
    "current_cash_krw": 12000000,
    "monthly_history": [
      {
        "month": "2026-06",
        "revenue_krw": 30000000,
        "transaction_count": 3000,
        "variable_costs": {
          "ingredients_krw": 9000000,
          "platform_fee_krw": 3000000,
          "payment_fee_krw": 600000
        },
        "fixed_costs": {
          "rent_krw": 4000000,
          "labor_krw": 7000000,
          "utilities_krw": 1000000,
          "other_krw": 500000
        },
        "tax_cash_outflow_krw": 0,
        "capital_expenditure_krw": 0
      }
    ],
    "loans": [],
    "cost_exposures": {
      "imported_ingredient_share": 0.25,
      "variable_rate_debt_share": 0
    },
    "schema_version": "store_profile.v1"
  },
  "research_request": {
    "run_id": "RUN-20260728-001",
    "tenant_id": "default",
    "as_of_date": "2026-07-28",
    "forecast_start": "2026-08-01",
    "forecast_end": "2026-09-30",
    "store_profile_snapshot_id": "STORE-SNAPSHOT-001",
    "business_type_code": "FNB_CAFE",
    "ingredient_categories": ["COFFEE_BEAN"],
    "platform_usage": [],
    "store_location": {
      "address": "서울특별시 강남구 테헤란로 123",
      "latitude": 37.4979,
      "longitude": 127.0276,
      "administrative_area": "서울특별시 강남구"
    },
    "administrative_area_codes": ["11680"],
    "search_radius_m": 1500,
    "official_indicator_snapshot_ids": [],
    "event_registry_version": "event_types.v1",
    "source_policy_version": "source_tiers.v1"
  },
  "official_data_requests": []
}
```

금액과 비율은 JSON 숫자 또는 문자열로 보낼 수 있지만 서버 내부에서는 `Decimal`로 검증합니다. 계약에 없는 필드는 거부합니다. 실제 공식 지표를 포함하려면 `official_data_requests`에 제공자별 요청을 추가합니다.

```json
{
  "provider": "ECOS",
  "indicator_id": "BASE_RATE",
  "request_params": {
    "stat_code": "722Y001",
    "item_code": "0101000",
    "period_type": "M",
    "start_date": "202501",
    "end_date": "202607"
  },
  "required": false,
  "max_age_days": 90,
  "target_frequency": "MONTHLY",
  "transform": "LAST"
}
```

지원 제공자 이름은 `ECOS`, `KOSIS`, `CUSTOMS`, `PUBLIC_DATA`입니다. 공식 응답에 신뢰 가능한 발표·가용 시점이 없으면 관측값은 추적 정보에는 남을 수 있지만 계산 특성값에는 포함되지 않습니다.

## 비동기 제출, 작업 상태, 멱등성

`POST /v1/analyses`는 HTTP 202와 `run_id`, 상태·결과 URL을 반환합니다. 선택적으로 다음 헤더를 보낼 수 있습니다.

```http
Idempotency-Key: store-001-2026-07-28-v1
X-Correlation-ID: client-request-123
```

- 같은 테넌트와 멱등성 키의 저장된 결과가 있으면 기존 결과를 재사용합니다.
- 같은 `run_id`에 다른 요청 본문을 재사용하면 HTTP 409를 반환합니다.
- 작업 상태와 구조화 오류는 `analysis_jobs`에 저장됩니다.
- 현재 실행기는 `in_process`이므로 실행 중인 작업은 프로세스 재시작 후 이어지지 않습니다.
- MVP는 `tenant_id=default`만 지원합니다.

상태 조회는 `GET /v1/analyses/{run_id}`로, 결과 조회는 `GET /v1/analyses/{run_id}/result`로 수행합니다.

## 결과 구조

| 필드 | 내용 |
| --- | --- |
| `status`, `sections` | 전체 및 입력·공식·예측·조사·신호·금융·정책 섹션 상태 |
| `input_snapshot` | 분석에 사용한 점포·조사·공식 요청 스냅샷 |
| `official_data` | 관측값, 시점 정보, 신선도, 수집 결과와 제공자 오류 |
| `official_features` | 월별 특성값과 관측값→예측값 변환 기여도 |
| `baseline` | 선택 모델, 검증 지표, 월별 하한·중앙·상한 |
| `forecast_layer_comparisons` | 추세·기준·저영향·고영향 계층 간 월별 금융 차이와 귀속 |
| `research` | 에이전트 묶음, 단계별 집계, 참고 정보, 확정·거절 후보와 실패 정보 |
| `signals`, `adjustments` | 검증 이벤트의 점포 신호와 월별 시나리오 조정 |
| `scenarios` | 월별 현금흐름, BEP, 현금 고갈과 유동성 위험 |
| `policies` | 후보, 출처·마감 검증, 적격성, 효과, 단계별 수와 정렬 |
| `grounded_summary` | 결과·근거 ID에 연결된 결정형 문장 |
| `traceability`, `versions`, `evidence_replay` | 데이터·모델·계수·규칙·재생·결과 버전 정보 |
| `warnings`, `limitations`, `section_status_summary` | 부분 결과 사유와 독립 섹션의 이용 가능성 |

`research.rejected_events`는 원래 후보 필드, 검증 실패와 신호 적격성, 증거, 재시도 결과를 보존합니다. 확정되지 않은 후보는 이벤트 ID가 없으므로 `/v1/event-candidates/{candidate_id}/evidence`로 근거를 조회해야 합니다.

## 가정 시나리오(What-if)

```http
POST /v1/analyses/RUN-20260728-001/what-if
Content-Type: application/json
```

```json
{
  "scenario_name": "WHAT_IF_REVENUE_DOWN_10",
  "revenue_multiplier": 0.9,
  "variable_cost_multiplier": 1,
  "fixed_cost_multiplier": 1,
  "interest_rate_delta": 0.01
}
```

서버는 저장된 기준 예측을 사용해 금융 계산을 다시 실행하고 추가 전용 결과 버전을 만듭니다. `interest_rate_delta=0.01`은 1%p 상승을 뜻합니다. 프론트엔드나 AI 클라이언트가 금융 계산을 다시 구현하면 안 됩니다.

## 실패·부분 결과 규칙

- 과거 매출과 `declared_monthly_revenue_krw`가 모두 없으면 기준 예측은 `INSUFFICIENT_DATA`입니다.
- 금융 계산에는 최소 1개의 `monthly_history`가 필요합니다.
- 제공자 미설정·실패·오래된 데이터는 `provider_errors`, `missing_indicators`, 해당 섹션의 `PARTIAL`로 남습니다.
- 검증 실패 이벤트는 `research.rejected_events`에 남지만 `signals`에는 포함되지 않습니다.
- 정책 조건 입력이 없으면 `NEEDS_INFORMATION`이며 실제 승인 가능으로 표현하지 않습니다.
- 예측 기간 내 현금이 고갈되지 않으면 `cash_burn_date=null`, `NO_BURN_WITHIN_HORIZON`입니다.
- 지오코딩 실패는 `GEO_PROVIDER_NOT_CONFIGURED`, `GEO_PROVIDER_ERROR`, `GEO_NOT_FOUND`, `LOCATION_AMBIGUOUS`, `OUTSIDE_SEARCH_RADIUS`처럼 구분된 코드로 반환합니다.

## 주소 확인과 CSV 검증

`POST /v1/locations/geocode`는 `{ "address": "..." }`를 받아 정규화 주소, 위도·경도, `geocode_status`, 제공자, 후보 수와 실패 사유를 반환합니다. 좌표를 찾지 못하면 추정하지 않고 `null` 좌표와 실패 상태를 반환합니다. `fake` 모드에서는 E2E용 합성 주소만 `DETERMINISTIC_FIXTURE`로 확인합니다.

`POST /v1/inputs/csv/validate`는 파일 업로드가 아닌 파싱된 행 배열을 받습니다.

```json
{
  "rows": [
    {
      "schema_version": "store_history.v1",
      "month": "2026-06",
      "revenue_krw": "30000000",
      "variable_costs_krw": "12600000",
      "fixed_costs_krw": "12500000"
    }
  ]
}
```

필수 열과 오류 코드는 `backend/src/ingestion/user_input/parser.py` 및 OpenAPI 계약을 확인하세요. 제공자 키는 서버 환경변수에만 두고 `VITE_*`에 넣지 않습니다.

## 호환 경로

`/v1/analysis`, `/v1/analysis/sync`, `/v1/research/{run_id}`, `/v1/sources/{source_id}`, `/v1/events`는 초기 연구 API 호환 경로입니다. 표준 인증 의존성과 구성이 다를 수 있으므로 제거 또는 인증 일원화 전까지 내부 개발 호환 용도로만 사용합니다.
