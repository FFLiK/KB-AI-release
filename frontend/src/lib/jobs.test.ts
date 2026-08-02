import { describe, expect, it } from "vitest";
import {
  canOpenJobResult,
  isTerminalJobState,
  jobPollingInterval,
  jobStateLabel,
  normalizeJobState,
} from "./jobs";

describe("job states", () => {
  it.each(["COMPLETED", "PARTIAL", "FAILED", "CANCELLED"])(
    "classifies %s as terminal",
    (state) => expect(isTerminalJobState(state)).toBe(true),
  );
  it("normalizes enum-qualified backend values", () =>
    expect(normalizeJobState("AnalysisRunStatus.COMPLETED")).toBe("COMPLETED"));
  it("opens only usable terminal results", () => {
    expect(canOpenJobResult("PARTIAL")).toBe(true);
    expect(canOpenJobResult("FAILED")).toBe(false);
  });
  it("backs off in hidden tabs and stops on terminal states", () => {
    expect(jobPollingInterval("RUNNING", false)).toBe(1000);
    expect(jobPollingInterval("RUNNING", true)).toBe(3000);
    expect(jobPollingInterval("COMPLETED", false)).toBe(false);
  });
  it("maps states to Korean labels", () =>
    expect(jobStateLabel("QUEUED")).toBe("대기 중"));
});
