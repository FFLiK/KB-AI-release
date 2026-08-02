import { describe, expect, it } from "vitest";
import {
  createAnalysisRequest,
  createOfficialDataRequests,
  createWhatIfRequest,
  sampleForm,
  sampleHistory,
} from "./request";

describe("request mapping", () => {
  it("maps form rows without recalculating financial values", () => {
    const request = createAnalysisRequest(
      sampleForm,
      sampleHistory,
      "RUN-TEST",
      { latitude: "37.5", longitude: "127.03" },
    );
    expect(request.research_request.run_id).toBe("RUN-TEST");
    expect(request.store_profile.monthly_history?.[0]?.revenue_krw).toBe(
      "24800000",
    );
    expect(request.store_profile.latitude).toBe(37.5);
    expect(request.store_profile.forecast_horizon_months).toBe(6);
    expect(request.research_request.forecast_end).toBe("2027-01-31");
    expect(
      request.official_data_requests?.map((item) => item.indicator_id),
    ).toEqual([
      "BASE_RATE",
      "USD_KRW",
      "IMPORT_PRICE_INDEX_USD",
      "CONSUMER_PRICE_INDEX",
      "CUSTOMS_IMPORT_UNIT_PRICE_USD_PER_KG_HS0901110000",
    ]);
    expect(request.official_data_requests?.[0]?.request_params).toMatchObject({
      start_date: "202506",
      end_date: "202606",
    });
  });
  it("builds a trailing official-data window from the analysis date", () => {
    const requests = createOfficialDataRequests("2025-02-15");
    expect(requests[0]?.request_params).toMatchObject({
      start_date: "202401",
      end_date: "202501",
    });
  });
  it("converts percentages and percentage points at the API boundary", () => {
    expect(
      createWhatIfRequest({
        scenarioName: "test",
        revenuePercent: "-10",
        variablePercent: "5",
        fixedPercent: "0",
        interestPercentagePoints: "1",
      }),
    ).toEqual({
      scenario_name: "test",
      revenue_multiplier: 0.9,
      variable_cost_multiplier: 1.05,
      fixed_cost_multiplier: 1,
      interest_rate_delta: 0.01,
    });
  });
});
