import { jobStateLabel } from "../../lib/jobs";

const labels: Record<string, string> = {
  COMPLETED: "완료",
  PARTIAL: "일부 완료",
  FAILED: "실패",
  MISSING: "누락",
  SKIPPED: "건너뜀",
  UNKNOWN: "미확인",
  RETRYABLE: "재시도 가능",
  EXTRACTED: "추출됨",
  ACCEPTED: "승인됨",
  VALID: "유효",
  STALE: "오래됨",
  REVISED: "수정됨",
  ACCESSIBLE: "접근 가능",
  INACCESSIBLE: "접근 불가",
  REVENUE: "매출",
  INGREDIENT_COST: "재료비",
  OTHER_VARIABLE_COST: "기타 변동비",
  FIXED_COST: "고정비",
  INTEREST: "이자",
  PRINCIPAL: "원금",
  TAX: "세금",
  CAPEX: "자본적 지출",
  OTHER_INFLOW: "기타 현금 유입",
  REVENUE_DEMAND: "매출 수요",
  DOMESTIC_INGREDIENT_COST: "국내 재료비",
  IMPORTED_INGREDIENT_COST: "수입 재료비",
  INTEREST_RATE: "금리",
  INTEREST_PAYMENT: "이자 지급액",
  NONE: "직접 반영 없음",
  UNMAPPED: "연결되지 않음",
  INCREASE: "증가",
  DECREASE: "감소",
  NEUTRAL: "중립",
  LOCAL_EVENT: "지역 이벤트 조사",
  INDUSTRY_EVENT: "산업 이벤트 조사",
  MACRO_ECONOMY: "거시경제 조사",
  POLICY_REGULATION: "정책·규제 조사",
  NO_VALIDATED_SIGNAL_ELIGIBLE_EVENT: "전망에 반영할 주요 이슈 없음",
  SIGNAL_DISABLED_EVENT_TYPE: "전망 미반영 이벤트 유형",
  SOURCE_ACCESS_FAILURES: "출처 접근 실패",
  DATE_PARSE_FAILED: "날짜 해석 실패",
  QUOTE_NOT_FOUND: "인용문 확인 실패",
  OFFSET_MISMATCH: "인용 위치 불일치",
  SOURCE_UNAVAILABLE: "출처 확인 불가",
  SOURCE_UNTRUSTED: "출처 신뢰 기준 미충족",
  FORECAST_WINDOW_NOT_OVERLAPPED: "예측 기간과 겹치지 않음",
  OUTSIDE_SEARCH_RADIUS: "검색 반경 밖 이벤트",
  INDUSTRY_NOT_RELEVANT: "업종 관련성 부족",
  MISSING_REQUIRED_FIELD: "필수 항목 누락",
  ENUM_NOT_ALLOWED: "허용되지 않은 분류값",
  DIRECTION_MECHANISM_NOT_ALLOWED: "영향 방향과 메커니즘 조합 오류",
  MECHANISM_NOT_SUPPORTED: "지원하지 않는 영향 메커니즘",
  NO_OBSERVATIONS: "관측값 없음",
  NO_VALID_OBSERVATIONS: "유효한 관측값 없음",
  PROVIDER_NOT_CONFIGURED: "제공기관 연결 미설정",
  PROVIDER_ERROR: "제공기관 요청 오류",
  PROJECTED: "예측 입력",
  OBSERVED: "관측값",
  NO_BURN_WITHIN_HORIZON: "예측 기간 내 현금 소진 없음",
  BURN_WITHIN_HORIZON: "예측 기간 내 현금 소진 예상",
  NO_LIQUIDITY_RISK_WITHIN_HORIZON: "예측 기간 내 유동성 위험 없음",
  NOT_STARTED: "시작 전",
  NOT_ATTEMPTED: "시도하지 않음",
  CANCELLED: "취소됨",
  MACRO: "거시경제 조사",
  INDUSTRY: "업종 조사",
  LOCAL: "지역 조사",
  CANDIDATES_EXTRACTED: "관련 이슈 확인",
  REFERENCE_FINDINGS_ONLY: "참고 근거만 확인",
  NO_DISCRETE_EVENT: "개별 이벤트 없음",
  INSUFFICIENT_TEMPORAL_EVIDENCE: "시점 근거 부족",
  INSUFFICIENT_IMPACT_EVIDENCE: "영향 근거 부족",
  OUTSIDE_FORECAST_CONTEXT: "예측 맥락 밖",
  SOURCE_CONTENT_UNUSABLE: "출처 내용 사용 불가",
  DUPLICATE_SOURCE: "중복 출처",
  DUPLICATE_FINAL_URL_OR_BODY: "최종 주소 또는 본문 중복",
  NAVIGATION_ONLY: "탐색 메뉴 중심 문서",
  NAVIGATION_OR_LIST_PAGE: "목록·탐색 페이지",
  INSUFFICIENT_CONTENT: "본문 내용 부족",
  QUERY_IRRELEVANT: "검색 목적과 관련성 부족",
  STALE_SOURCE: "오래된 출처",
  UNVERIFIED_SOURCE_TIER: "출처 등급 추가 확인 필요",
  INPUT_TRUNCATED: "입력 길이 제한 적용",
  REDIRECT_EXPIRED: "검색 경유 주소 만료",
  REDIRECT_LIMIT: "주소 이동 횟수 초과",
  FINAL_DOMAIN_REJECTED: "최종 도메인 거부",
  NO_USABLE_SOURCES: "사용 가능한 출처 없음",
  SEARCH_REQUEST_TIMEOUT: "검색 요청 시간 초과",
  DOCUMENT_FETCH_TIMEOUT: "문서 수집 시간 초과",
  ATTACHMENT_FETCH_TIMEOUT: "첨부파일 수집 시간 초과",
  EXTRACTION_REQUEST_TIMEOUT: "구조화 추출 시간 초과",
  ANALYSIS_JOB_TIMEOUT: "전체 분석 작업 시간 초과",
  USER_CANCELLED: "사용자 취소",
  AGENT_WALL_CLOCK_DEADLINE_EXHAUSTED: "에이전트 실행 제한 소진",
  AGENT_WALL_CLOCK_RESERVE_REACHED: "후속 처리 시간 예약",
  DOCUMENT_COLLECTION_INCOMPLETE: "문서 수집 미완료",
  SEARCH_RESULTS_FETCH_FAILED: "검색 결과 문서 수집 실패",
  DOCUMENTS_REJECTED_BY_QUALITY: "문서 품질 검증 탈락",
  POLICY_EXTRACTION_INCOMPLETE: "정책 추출 미완료",
  SEARCH_DISCOVERY: "검색 발견",
  SEED_COLLECTION: "공식 출처 우선 수집",
  DOCUMENT_FETCH: "문서 수집",
  EVENT_EXTRACTION: "이벤트 추출",
  POLICY_EXTRACTION: "정책 추출",
  seed_collection: "공식 출처 수집",
  search_discovery: "검색 발견",
  document_fetching: "문서 수집",
  detail_traversal: "상세 페이지 탐색",
  attachment_processing: "첨부파일 처리",
  extraction: "구조화 추출",
  validation: "검증",
  result_aggregation: "결과 집계",
  EXTRACTION_DEGRADED: "추출 단계 일부 실패",
  POLICY_EXTRACTION_FAILED: "정책 구조화 추출 실패",
  NO_POLICY_CANDIDATES: "정책 후보 없음",
  STRICT_EVENT_REQUIREMENTS_MISSING: "이벤트 정보 부족",
  STRICT_EVENT_TEMPORAL_AND_IMPACT_EVIDENCE: "시점·재무 영향 근거 부족",
  REVIEW_SOURCE: "출처 추가 검토",
  REFERENCE_ONLY: "참고 전용",
  DISCOVERED: "발견",
  VALIDATED: "검증 완료",
  SIGNAL_ELIGIBLE: "전망 반영 가능",
  EXCLUDED_BY_DISTANCE: "거리 기준 제외",
  SIGNAL_GENERATED: "전망 반영",
  FINANCIALLY_APPLIED: "재무 반영",
  GEO_PROVIDER_NOT_CONFIGURED: "주소 확인 서비스 준비 중",
  GEO_PROVIDER_ERROR: "주소 확인 서비스 오류",
  LOCATION_AMBIGUOUS: "위치 후보 모호",
  NO_VARIABLE_RATE_DEBT_EXPOSURE: "변동금리 부채 노출 없음",
  NOT_EVALUATED_DUE_TO_VALIDATION_GATE: "정보 부족으로 영향 미평가",
  RELEVANT: "재무 노출 관련",
  APPLIED: "임시 적용",
  EXPIRED: "자동 만료",
  INELIGIBLE: "적용 조건 미충족",
  NEWER_OFFICIAL_EVENT_BRIDGES_STALE_SERIES:
    "최신 공식 이벤트로 관측 시차 보정",
  OFFICIAL_SERIES_CAUGHT_UP: "공식 관측 시리즈 반영 완료",
  VALUE_OR_UNIT_NOT_EXPLICITLY_EVIDENCED: "값 또는 단위의 명시 근거 부족",
  SOURCE_NOT_OFFICIAL_PRIMARY: "공식 1차 출처가 아님",
  NO_OFFICIAL_BASELINE_OBSERVATION: "비교할 공식 기준 관측 없음",
  EVENT_NOT_EFFECTIVE_AS_OF_ANALYSIS: "분석 기준일 현재 미시행",
  INDICATOR_MISMATCH: "공식 지표 불일치",
  UNIT_MISMATCH: "공식 지표 단위 불일치",
  POLICY_SOURCE_MISSING: "정책 출처 누락",
  POLICY_SOURCE_SET_MISMATCH: "정책 출처 집합 불일치",
  POLICY_SOURCE_UNAVAILABLE: "정책 출처 접근 불가",
  POLICY_SOURCE_SECURITY_REJECTED: "정책 출처 확인 실패",
  POLICY_SOURCE_UNTRUSTED: "정책 출처 신뢰 기준 미충족",
  POLICY_EVIDENCE_SOURCE_MISSING: "정책 근거 출처 누락",
  POLICY_REVISION_MISMATCH: "정책 출처 개정본 불일치",
  POLICY_QUOTE_NOT_FOUND: "정책 근거 인용문 미발견",
  POLICY_OFFSET_AMBIGUOUS: "정책 근거 위치 모호",
  LIQUIDITY_RISK_WITHIN_HORIZON: "예측 기간 내 유동성 위험 예상",
  NOT_VALIDATED: "추가 확인 필요",
  NEEDS_INFORMATION: "정보 필요",
  ELIGIBLE: "신청 가능",
  CLOSED: "접수 종료",
  INTEREST_SUBSIDY: "이자 지원",
  CREDIT_GUARANTEE: "신용보증",
  LOAN_SUPPORT: "융자 지원",
  UNTIL_FUNDS_EXHAUSTED: "예산 소진 시까지",
  PERCENT: "%",
  KRW_PER_USD: "원/달러",
  INDEX_2020_100: "2020=100",
  USD_PER_KG: "달러/kg",
};

const indicators: Record<string, string> = {
  BASE_RATE: "한국은행 기준금리",
  USD_KRW: "원/달러 월평균 환율",
  IMPORT_PRICE_INDEX_USD: "수입물가지수(달러 기준)",
  CONSUMER_PRICE_INDEX: "소비자물가지수",
  CUSTOMS_IMPORT_UNIT_PRICE_USD_PER_KG_HS0901110000: "커피 생두 수입 단가",
  FOOD_PRICE_INDEX: "식품 물가지수",
  IMPORT_UNIT_PRICE_HS090111: "커피 생두 수입 단가",
};

const failureMessages: Record<string, string> = {
  DATE_PARSE_FAILED: "이벤트 날짜를 확인하지 못했습니다.",
  QUOTE_NOT_FOUND: "저장된 출처 개정본에서 근거 인용문을 찾지 못했습니다.",
  OFFSET_MISMATCH:
    "근거 인용문의 위치가 저장된 출처 개정본과 일치하지 않습니다.",
  SOURCE_UNAVAILABLE: "인용된 출처 개정본을 확인할 수 없습니다.",
  SOURCE_UNTRUSTED: "출처가 설정된 신뢰도 기준을 충족하지 못했습니다.",
  FORECAST_WINDOW_NOT_OVERLAPPED: "이벤트 기간이 예측 기간과 겹치지 않습니다.",
  OUTSIDE_SEARCH_RADIUS: "이벤트가 설정된 점포 검색 반경 밖에 있습니다.",
  INDUSTRY_NOT_RELEVANT: "이벤트와 점포 업종의 관련성을 확인하지 못했습니다.",
  MISSING_REQUIRED_FIELD: "이벤트 확인에 필요한 정보가 부족합니다.",
  ENUM_NOT_ALLOWED: "지원하지 않는 이벤트 분류입니다.",
  DIRECTION_MECHANISM_NOT_ALLOWED:
    "영향 방향과 발생 메커니즘의 조합이 허용되지 않습니다.",
  MECHANISM_NOT_SUPPORTED: "지원하지 않는 영향 메커니즘입니다.",
  NO_OBSERVATIONS: "요청한 기간에 사용할 수 있는 관측값이 없습니다.",
  NO_VALID_OBSERVATIONS:
    "제공기관 응답은 있었지만 분석 기준일에 사용할 수 있는 유효 관측값이 없습니다.",
  PROVIDER_NOT_CONFIGURED: "설정된 제공기관 어댑터를 사용할 수 없습니다.",
  PROVIDER_ERROR: "제공기관 데이터 요청 중 오류가 발생했습니다.",
};

const sectionLabels: Record<string, string> = {
  OFFICIAL_DATA: "공식 데이터",
  RESEARCH: "위험 조사",
  SIGNALS: "전망 반영",
  FINANCE: "재무 예측",
  POLICIES: "지원 정책",
  RISK_RESEARCH: "위험 조사",
  OFFICIAL: "공식 데이터",
  POLICY: "지원 정책",
};

const sectionEffects: Record<string, string> = {
  OFFICIAL_DATA:
    "공식 관측값과 이를 변환한 월별 예측 입력의 적용 상태를 나타냅니다.",
  RESEARCH: "외부 시장 이슈의 조사 상태를 표시합니다.",
  SIGNALS: "주요 이슈가 재무 시나리오에 반영됐는지 표시합니다.",
  FINANCE: "현금흐름·손익분기점·예측 계층 비교의 계산 상태입니다.",
  POLICIES:
    "정책 후보의 조사 상태입니다. 위험 이벤트 조사 상태에는 영향을 주지 않습니다.",
};

const assumptions: Record<string, string> = {
  "Feature projections are deterministic scenario inputs, not official forecasts":
    "공식 지표를 바탕으로 구성한 월별 분석값입니다.",
  "Projected model input; not an official agency forecast":
    "월별 전망에 반영한 분석값입니다.",
  "Recent relative change is capped to +/-5% before projection":
    "최근 상대 변화율은 예측 전에 ±5%로 제한합니다.",
  "Each future incremental change decays by 0.65":
    "미래의 추가 변화는 매월 0.65 비율로 감쇠합니다.",
  "DECAYED_CAPPED_RECENT_CHANGE_V2 applies a 0.65 decay to each future shock":
    "감쇠·상한 v2 변환은 미래 충격에 0.65 감쇠율을 적용합니다.",
  "Projected levels are bounded and are scenario inputs, not agency forecasts":
    "예측 수준에는 상한이 있으며 기관 전망이 아닌 시나리오 입력입니다.",
  "Recent change is capped to +/-5%, decays by 0.65, and has role-specific horizon caps":
    "최근 변화는 ±5%로 제한하고 0.65로 감쇠하며 역할별 누적 상한을 적용합니다.",
};

const uiMessages: Record<string, string> = {
  "Forecast intervals and policy effects are decision-support estimates, not guarantees.":
    "예측 구간은 입력 데이터와 분석 기준일을 바탕으로 산출했습니다.",
  "Policy availability and final eligibility require confirmation by the official provider.":
    "정책 세부 조건과 신청 일정은 제공기관 안내를 함께 확인해 주세요.",
};

const normalizeCode = (value: unknown) =>
  String(value ?? "UNKNOWN")
    .split(".")
    .at(-1) ?? "UNKNOWN";

export const analysisStatusLabel = (value: unknown) => {
  const code = normalizeCode(value);
  return labels[code] ?? jobStateLabel(code);
};
export const analysisCodeLabel = (value: unknown) => {
  const raw = String(value ?? "UNKNOWN");
  if (raw.startsWith("OPTIONAL_OFFICIAL_INDICATOR_MISSING:")) {
    return "선택 공식 지표의 관측값이 없어 제외했습니다.";
  }
  const code = normalizeCode(raw);
  return labels[code] ?? code;
};
export const indicatorLabel = (id: string, fallback?: string | null) =>
  indicators[id] ?? fallback ?? id;
export const failureMessage = (code: string, fallback?: string | null) =>
  failureMessages[code] ?? fallback ?? analysisCodeLabel(code);
export const sectionLabel = (section: string, fallback?: string | null) => {
  const key = normalizeCode(section).toUpperCase().replaceAll(" ", "_");
  return sectionLabels[key] ?? fallback ?? section;
};
export const sectionEffect = (section: string, fallback?: string | null) => {
  const key = normalizeCode(section).toUpperCase().replaceAll(" ", "_");
  return (
    sectionEffects[key] ??
    sectionEffects[key.replace("RISK_", "")] ??
    fallback ??
    section
  );
};
export const assumptionLabel = (value: string) => assumptions[value] ?? value;
export const uiMessageLabel = (value: string) =>
  value.startsWith("PARTIAL_RESULT:")
    ? "일부 항목은 사용할 수 있는 데이터 범위에서 결과를 제공했습니다."
    : (uiMessages[value] ?? value);
export const signalEligibilityLabel = (enabled: boolean) =>
  enabled
    ? "재무 전망 반영 가능 이벤트 유형입니다."
    : "참고 정보로만 표시하고 현금흐름 전망에는 반영하지 않습니다.";

export const policyReasonLabel = (value: unknown) => {
  const reason = String(value ?? "").trim();
  if (!reason) return "대상 조건과 신청 일정을 추가로 확인해 주세요.";
  if (reason.startsWith("Official evidence validation failed:")) {
    return "공식 안내에서 일부 조건을 확인하지 못했습니다. 상세 안내에서 최신 조건을 확인해 주세요.";
  }
  if (
    reason ===
    "The official program is closed and remains visible for traceability"
  ) {
    return "접수가 종료된 정책으로, 참고할 수 있도록 함께 표시합니다.";
  }
  return labels[normalizeCode(reason)] ?? reason;
};
