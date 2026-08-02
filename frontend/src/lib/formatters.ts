export const UNKNOWN_VALUE = "—";

export function formatWon(value: unknown): string {
  if (value === null || value === undefined || value === "")
    return UNKNOWN_VALUE;
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return UNKNOWN_VALUE;
  return new Intl.NumberFormat("ko-KR", {
    style: "currency",
    currency: "KRW",
    maximumFractionDigits: 0,
  }).format(numeric);
}

export function formatPercent(value: unknown, digits = 1): string {
  if (value === null || value === undefined || value === "")
    return UNKNOWN_VALUE;
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return UNKNOWN_VALUE;
  return `${new Intl.NumberFormat("ko-KR", { maximumFractionDigits: digits }).format(numeric * 100)}%`;
}

export function formatPercentagePoints(value: unknown, digits = 1): string {
  if (value === null || value === undefined || value === "")
    return UNKNOWN_VALUE;
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return UNKNOWN_VALUE;
  return `${new Intl.NumberFormat("ko-KR", { maximumFractionDigits: digits }).format(numeric * 100)}%p`;
}

export function formatDate(value: unknown): string {
  if (value === null || value === undefined || value === "")
    return UNKNOWN_VALUE;
  const parsed = new Date(String(value));
  if (Number.isNaN(parsed.valueOf())) return UNKNOWN_VALUE;
  return new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium" }).format(
    parsed,
  );
}

export function renderNullable(value: unknown, formatter = String): string {
  return value === null || value === undefined
    ? UNKNOWN_VALUE
    : formatter(value);
}
