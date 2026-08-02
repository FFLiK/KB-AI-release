# 합성 데모 안내

## 목적과 범위

`demo/`의 파일은 기능 확인과 재현 검증을 위한 합성 데이터입니다. 실제 뉴스, 공고, 정책, 지역 이벤트 또는 점포 데이터가 아니며 반드시 `SYNTHETIC_DEMO_ONLY` 상태를 유지해야 합니다.

합성 데모는 최종 재무 결과를 그대로 주입하지 않습니다. 검색, 문서 수집과 구조화 추출만 통제된 재생 데이터로 대체하고, 이후 이벤트 검증, 신호 생성, 예측과 금융 계산은 일반 분석과 동일한 코드 경로를 통과합니다.

## 데이터셋

| 데이터셋 ID | 상황 | 재무 축 | 검증 관점 |
| --- | --- | --- | --- |
| `cafe-gangnam-festival.v1` | 점포에서 40m 떨어진 장소의 강남 커피거리 축제 | `REVENUE_DEMAND` 증가 | 시간·위치·영향 근거를 통과한 이벤트가 매출 수요 신호와 현금흐름 변화로 연결됨 |
| `cafe-import-cost-shock.v1` | 2026년 7~12월 아라비카 원두 공급 차질 | `INGREDIENT_COST` 증가 | 서로 보강하는 두 출처가 기간과 공급 변화를 뒷받침하고 원재료비·기말 현금·BEP가 변함 |

각 데이터셋에는 다음 정보가 포함됩니다.

- 공통 카페 점포 입력
- 결정론적 검색 순서인 `discovery_replay`
- 개정 식별자와 인용 구간을 가진 `source_documents`
- 금융 신호가 될 수 없는 `reference_findings`
- 검증에서 제외될 `rejected_candidates`
- 검증을 통과할 `accepted_events`
- 예상 재무 축과 적용 월을 설명하는 `signal_blueprint`

후보 수가 여러 건이어도 검증 결과 하나만 재무에 적용될 수 있습니다. 이는 자료가 부족해서가 아니라 검증 단계를 통과한 항목만 신호가 되도록 설계했기 때문입니다.

## 설정과 실행

`backend/.env`에 다음 값을 설정하고 백엔드를 다시 시작합니다.

```env
RESEARCH_PROVIDER_MODE=demo_replay
ENABLE_DEMO_DATASETS=1
DEMO_DATASET_ID=cafe-gangnam-festival.v1
DEMO_DATASET_ROOT=
```

- 축제 시나리오: `DEMO_DATASET_ID=cafe-gangnam-festival.v1`
- 원재료비 시나리오: `DEMO_DATASET_ID=cafe-import-cost-shock.v1`
- `DEMO_DATASET_ROOT`가 비어 있으면 저장소의 `demo/`를 사용합니다.

현재 PowerShell 세션에 `RESEARCH_PROVIDER_MODE=fake` 또는 `real`이 설정되어 있으면 프로세스 환경 변수가 `.env`보다 우선합니다. 해당 변수를 제거하거나 `demo_replay`로 변경한 뒤 서버를 다시 시작합니다.

백엔드와 프론트엔드를 일반 실행 방식으로 시작한 뒤 화면에서 분석을 제출하거나 `POST /v1/analyses`를 호출합니다. 이 모드에서는 다음 구성요소가 합성 자료를 제공합니다.

- `DemoReplaySearchProvider`: 통제된 검색 결과
- `DemoReplayDocumentFetcher`: 네트워크를 사용하지 않는 원문
- `DemoReplayEventExtractor`: 근거가 연결된 이벤트 후보

선택된 조사 에이전트와 표준 검증기, 신호 생성기, 예측기, 금융 계산기는 그대로 실행됩니다.

## 검증 흐름

```text
합성 검색 결과
  → 합성 원문과 개정 식별자 저장
  → 이벤트 후보와 인용 근거 생성
  → 출처·근거·날짜·위치·업종 검증
  → 중복·충돌·적용 가능성 판정
  → 점포 신호 생성
  → 저영향·고영향 시나리오 계산
  → 기말 현금과 BEP 변화 표시
```

`expected_pipeline`은 재생할 근거와 예상 후보를 정의하지만 재무 결과를 직접 제공하지 않습니다. 후보가 저장된 실제 출처 개정 식별자를 인용하고 모든 검증·노출 조건을 통과해야 `FINANCIALLY_APPLIED` 상태가 됩니다.

## 운영 안전장치

- 기본값은 `ENABLE_DEMO_DATASETS=0`으로 유지합니다.
- 배포 환경에서는 `demo_replay`를 사용하지 않습니다.
- `.example` 주소로 네트워크 요청을 보내지 않습니다.
- 합성 출처와 실제 조사 출처를 같은 실행에 섞지 않습니다.
- 합성 결과를 실제 뉴스·공고·정책·이벤트 또는 실제 제공자 호출 성공으로 제시하지 않습니다.
- 데이터셋 본문을 변경하면 개정 식별자를 함께 갱신하고 회귀 테스트를 실행합니다.

전체 실행 절차는 [OPERATIONS.md](OPERATIONS.md), 검증 명령은 [TESTING.md](TESTING.md), 현재 통과 결과는 [TEST_RESULTS.md](TEST_RESULTS.md)를 참고하세요.
