import { describe, expect, it } from "vitest";
import {
  formatDate,
  formatPercentagePoints,
  formatPercent,
  formatWon,
  renderNullable,
} from "./formatters";

describe("Korean formatters", () => {
  it("formats won, percent, percentage points and dates", () => {
    expect(formatWon(1234567)).toContain("1,234,567");
    expect(formatPercent("0.125")).toBe("12.5%");
    expect(formatPercentagePoints("0.0125")).toBe("1.3%p");
    expect(formatDate("2026-07-29")).toMatch(/2026/);
  });
  it("preserves zero while rendering null as unknown", () => {
    expect(formatWon(0)).not.toBe("—");
    expect(renderNullable(0)).toBe("0");
    expect(formatWon(null)).toBe("—");
    expect(formatDate(null)).toBe("—");
  });
});
