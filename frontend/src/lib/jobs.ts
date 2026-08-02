export const TERMINAL_JOB_STATES = [
  "COMPLETED",
  "PARTIAL",
  "FAILED",
  "CANCELLED",
] as const;

export function normalizeJobState(value: unknown): string {
  return (
    String(value ?? "QUEUED")
      .split(".")
      .at(-1) ?? "QUEUED"
  );
}

export function isTerminalJobState(value: unknown): boolean {
  return TERMINAL_JOB_STATES.includes(
    normalizeJobState(value) as (typeof TERMINAL_JOB_STATES)[number],
  );
}

export function canOpenJobResult(value: unknown): boolean {
  return ["COMPLETED", "PARTIAL"].includes(normalizeJobState(value));
}

export function jobStateLabel(value: unknown): string {
  const state = normalizeJobState(value);
  return (
    (
      {
        QUEUED: "대기 중",
        RUNNING: "분석 중",
        COMPLETED: "완료",
        PARTIAL: "일부 완료",
        FAILED: "실패",
        CANCELLED: "취소됨",
        REJECTED: "거절됨",
        RETRYABLE: "재시도 가능",
        EXTRACTED: "추출됨",
        ACCEPTED: "승인됨",
        SKIPPED: "건너뜀",
        MISSING: "누락",
        UNKNOWN: "미확인",
        VALID: "유효",
        STALE: "오래됨",
        REVISED: "수정됨",
        ELIGIBLE: "조건 충족",
        INELIGIBLE: "조건 미충족",
        NEEDS_INFORMATION: "정보 필요",
        REFERENCE_ONLY: "참고 전용",
        NORMAL: "정상",
        UNATTAINABLE: "도달 불가",
        INSUFFICIENT_DATA: "데이터 부족",
      } as Record<string, string>
    )[state] ?? state
  );
}

export function jobPollingInterval(
  value: unknown,
  hidden = document.hidden,
): number | false {
  if (isTerminalJobState(value)) return false;
  return hidden ? 3_000 : 1_000;
}
