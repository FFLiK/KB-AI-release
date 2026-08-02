import type { components } from "./generated/schema";

const useDevelopmentProxy =
  import.meta.env.DEV &&
  new URLSearchParams(window.location.search).get("api") === "proxy";
export const API_BASE = useDevelopmentProxy
  ? "/api"
  : (import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000");
export type JobStatus = components["schemas"]["AnalysisStatusResponse"];
export type Result = components["schemas"]["AnalysisResultV1"];
export type GeocodeResponse = components["schemas"]["GeocodeResponse"];
export type CsvValidationResponse = components["schemas"]["ParseResult"];
export type WhatIfResponse = components["schemas"]["WhatIfResponse"];
export type EventEvidenceResponse =
  components["schemas"]["EventEvidenceResponse"];
export type CandidateEvidenceResponse =
  components["schemas"]["CandidateEvidenceResponse"];
export type PolicyDetailResponse =
  components["schemas"]["PolicyDetailResponse"];

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public correlationId?: string,
    public details?: unknown,
    public fieldErrors: Record<string, string> = {},
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const STATUS_MESSAGES: Record<number, string> = {
  400: "요청 내용을 처리할 수 없습니다. 입력값을 확인해 주세요.",
  401: "서비스 인증 정보를 확인해 주세요.",
  403: "이 요청을 수행할 권한이 없습니다.",
  404: "요청한 분석 또는 결과를 찾을 수 없습니다.",
  409: "동일한 분석 요청이 이미 처리 중이거나 기준 결과를 사용할 수 없습니다.",
  422: "입력값을 확인해 주세요. 표시된 필드를 수정한 뒤 다시 시도하세요.",
  429: "요청 한도에 도달했습니다. 잠시 후 한 번만 다시 시도해 주세요.",
  503: "서비스 연결을 준비하고 있습니다. 잠시 후 다시 시도해 주세요.",
};

function fieldErrorsFrom(body: unknown): Record<string, string> {
  if (
    !body ||
    typeof body !== "object" ||
    !("detail" in body) ||
    !Array.isArray(body.detail)
  )
    return {};
  return Object.fromEntries(
    body.detail.flatMap((entry) => {
      if (!entry || typeof entry !== "object") return [];
      const item = entry as { loc?: unknown[]; msg?: unknown };
      const path = item.loc?.filter((part) => part !== "body").join(".");
      return path ? [[path, String(item.msg ?? "유효하지 않은 값")]] : [];
    }),
  );
}

export function normalizeHttpError(
  status: number,
  body: unknown,
  correlationId?: string,
): ApiError {
  const fallback = STATUS_MESSAGES[status] ?? "요청을 처리하지 못했습니다.";
  const detail =
    body && typeof body === "object" && "detail" in body ? body.detail : null;
  const safeDetail =
    typeof detail === "string" && !/traceback|stack|api[_ -]?key/i.test(detail)
      ? detail
      : null;
  return new ApiError(
    status,
    safeDetail ?? fallback,
    correlationId,
    body,
    fieldErrorsFrom(body),
  );
}

function requestHeaders(extra: HeadersInit | undefined): Headers {
  const result = new Headers(extra);
  if (!result.has("Content-Type"))
    result.set("Content-Type", "application/json");
  result.set("X-Correlation-ID", crypto.randomUUID());
  return result;
}

export async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: requestHeaders(init.headers),
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError(
        0,
        "요청 시간이 초과되었습니다. 분석 ID로 다시 확인해 주세요.",
      );
    }
    throw new ApiError(
      0,
      "서비스에 연결할 수 없습니다. 네트워크 연결을 확인한 뒤 다시 시도해 주세요.",
    );
  }
  const correlationId = response.headers.get("X-Correlation-ID") ?? undefined;
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok)
    throw normalizeHttpError(response.status, body, correlationId);
  return body as T;
}

export const api = {
  health: () => request<{ status: string }>("/health"),
  ready: () =>
    request<{ status: string; database?: string; queue?: string }>("/ready"),
  geocode: (address: string) =>
    request<GeocodeResponse>("/v1/locations/geocode", {
      method: "POST",
      body: JSON.stringify({ address }),
    }),
  validateCsv: (rows: unknown[]) =>
    request<CsvValidationResponse>("/v1/inputs/csv/validate", {
      method: "POST",
      body: JSON.stringify({ rows }),
    }),
  submit: (payload: components["schemas"]["AnalysisJobRequest"], key: string) =>
    request<components["schemas"]["JobAccepted"]>("/v1/analyses", {
      method: "POST",
      headers: { "Idempotency-Key": key },
      body: JSON.stringify(payload),
    }),
  job: (id: string) =>
    request<JobStatus>(`/v1/analyses/${encodeURIComponent(id)}`),
  result: (id: string, version?: number) =>
    request<Result>(
      `/v1/analyses/${encodeURIComponent(id)}/result${version ? `?version=${version}` : ""}`,
    ),
  whatIf: (id: string, payload: components["schemas"]["WhatIfRequest"]) =>
    request<WhatIfResponse>(`/v1/analyses/${encodeURIComponent(id)}/what-if`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  evidence: (id: string) =>
    request<EventEvidenceResponse>(
      `/v1/events/${encodeURIComponent(id)}/evidence`,
    ),
  candidateEvidence: (id: string) =>
    request<CandidateEvidenceResponse>(
      `/v1/event-candidates/${encodeURIComponent(id)}/evidence`,
    ),
  policy: (id: string) =>
    request<PolicyDetailResponse>(`/v1/policies/${encodeURIComponent(id)}`),
};
