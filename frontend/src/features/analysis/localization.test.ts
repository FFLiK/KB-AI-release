import { describe, expect, it } from "vitest";
import {
  analysisCodeLabel,
  analysisStatusLabel,
  failureMessage,
  indicatorLabel,
  uiMessageLabel,
} from "./localization";

describe("analysis UI localization", () => {
  it("localizes statuses, indicators and validation failures", () => {
    expect(analysisStatusLabel("RETRYABLE")).toBe("재시도 가능");
    expect(analysisStatusLabel("NO_BURN_WITHIN_HORIZON")).toBe(
      "예측 기간 내 현금 소진 없음",
    );
    expect(indicatorLabel("BASE_RATE")).toBe("한국은행 기준금리");
    expect(failureMessage("DATE_PARSE_FAILED")).toContain("날짜");
  });

  it("keeps unknown technical codes visible", () => {
    expect(analysisCodeLabel("NEW_TECHNICAL_CODE")).toBe("NEW_TECHNICAL_CODE");
  });

  it("localizes known decision-support limitations", () => {
    expect(
      uiMessageLabel(
        "Forecast intervals and policy effects are decision-support estimates, not guarantees.",
      ),
    ).toContain("입력 데이터와 분석 기준일");
  });
});
