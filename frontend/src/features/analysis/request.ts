import type { components } from "../../api/generated/schema";

export type AnalysisJobRequest = components["schemas"]["AnalysisJobRequest"];
export type WhatIfRequest = components["schemas"]["WhatIfRequest"];
type OfficialDataRequest = components["schemas"]["OfficialDataRequest"];

export type HistoryRow = {
  month: string;
  revenue: string;
  ingredients: string;
  rent: string;
  labor: string;
};

export type AnalysisForm = {
  name: string;
  storeId: string;
  address: string;
  cash: string;
  minimumCash: string;
  horizon: string;
  asOf: string;
  loan: string;
  rate: string;
};

export const sampleHistory: HistoryRow[] = [
  ["2026-01", "24800000", "7100000", "3200000", "6900000"],
  ["2026-02", "26400000", "7600000", "3200000", "6900000"],
  ["2026-03", "27900000", "8000000", "3200000", "6900000"],
  ["2026-04", "28600000", "8200000", "3200000", "6900000"],
  ["2026-05", "30100000", "8700000", "3200000", "6900000"],
  ["2026-06", "31600000", "9100000", "3200000", "6900000"],
].map(([month, revenue, ingredients, rent, labor]) => ({
  month,
  revenue,
  ingredients,
  rent,
  labor,
}));

export const sampleForm: AnalysisForm = {
  name: "강남 샘플 카페 (합성)",
  storeId: "DEMO-CAFE-2026",
  address: "서울특별시 강남구 테헤란로 152",
  cash: "18000000",
  minimumCash: "6000000",
  horizon: "6",
  asOf: "2026-07-29",
  loan: "25000000",
  rate: "5.2",
};

function forecastEnd(horizon: number): string {
  const end = new Date(Date.UTC(2026, 7 + horizon, 0));
  return end.toISOString().slice(0, 10);
}

function officialDataPeriod(asOf: string): { start: string; end: string } {
  const parsed = new Date(`${asOf}T00:00:00Z`);
  const safe = Number.isNaN(parsed.getTime())
    ? new Date(Date.UTC(2026, 6, 29))
    : parsed;
  const end = new Date(
    Date.UTC(safe.getUTCFullYear(), safe.getUTCMonth() - 1, 1),
  );
  const start = new Date(
    Date.UTC(end.getUTCFullYear(), end.getUTCMonth() - 12, 1),
  );
  const monthKey = (value: Date) =>
    `${value.getUTCFullYear()}${String(value.getUTCMonth() + 1).padStart(2, "0")}`;
  return { start: monthKey(start), end: monthKey(end) };
}

export function createOfficialDataRequests(
  asOf: string,
): OfficialDataRequest[] {
  const period = officialDataPeriod(asOf);
  return [
    {
      provider: "ECOS",
      indicator_id: "BASE_RATE",
      request_params: {
        stat_code: "722Y001",
        item_code: "0101000",
        period_type: "M",
        start_date: period.start,
        end_date: period.end,
      },
      required: false,
      max_age_days: 90,
      target_frequency: "MONTHLY",
      transform: "LAST",
    },
    {
      provider: "ECOS",
      indicator_id: "USD_KRW",
      request_params: {
        stat_code: "731Y004",
        item_code: "0000001",
        item_code2: "0000100",
        period_type: "M",
        start_date: period.start,
        end_date: period.end,
      },
      required: false,
      max_age_days: 90,
      target_frequency: "MONTHLY",
      transform: "LAST",
    },
    {
      provider: "ECOS",
      indicator_id: "IMPORT_PRICE_INDEX_USD",
      request_params: {
        stat_code: "401Y015",
        item_code: "*AA",
        item_code2: "D",
        period_type: "M",
        start_date: period.start,
        end_date: period.end,
      },
      required: false,
      max_age_days: 120,
      target_frequency: "MONTHLY",
      transform: "LAST",
    },
    {
      provider: "KOSIS",
      indicator_id: "CONSUMER_PRICE_INDEX",
      request_params: {
        orgId: "101",
        tblId: "DT_1J22003",
        objL1: "ALL",
        itmId: "T",
        prdSe: "M",
        startPrdDe: period.start,
        endPrdDe: period.end,
      },
      required: false,
      max_age_days: 120,
      target_frequency: "MONTHLY",
      transform: "LAST",
    },
    {
      provider: "CUSTOMS",
      indicator_id: "CUSTOMS_IMPORT_UNIT_PRICE_USD_PER_KG_HS0901110000",
      request_params: {
        strtYymm: period.start,
        endYymm: period.end,
        hsSgn: "090111",
      },
      required: false,
      max_age_days: 120,
      target_frequency: "MONTHLY",
      transform: "LAST",
    },
  ];
}
export function createAnalysisRequest(
  form: AnalysisForm,
  history: HistoryRow[],
  runId: string,
  coordinates?: { latitude: string | number; longitude: string | number },
): AnalysisJobRequest {
  const horizon = Number(form.horizon);
  return {
    store_profile: {
      store_id: form.storeId,
      schema_version: "store_profile.v1",
      business_type_code: "FNB_CAFE",
      address: form.address,
      latitude: coordinates ? Number(coordinates.latitude) : null,
      longitude: coordinates ? Number(coordinates.longitude) : null,
      minimum_operating_cash_krw: form.minimumCash,
      current_cash_krw: form.cash,
      forecast_horizon_months: horizon,
      monthly_history: history.map((row) => ({
        month: row.month,
        revenue_krw: row.revenue,
        transaction_count: 0,
        variable_costs: {
          ingredients_krw: row.ingredients,
          platform_fee_krw: "0",
          payment_fee_krw: "0",
        },
        fixed_costs: {
          rent_krw: row.rent,
          labor_krw: row.labor,
          utilities_krw: "0",
          other_krw: "0",
        },
        tax_cash_outflow_krw: "0",
        capital_expenditure_krw: "0",
      })),
      loans: form.loan
        ? [
            {
              loan_id: "LOAN-001",
              principal_balance_krw: form.loan,
              annual_interest_rate: String(Number(form.rate) / 100),
              rate_type: "FIXED",
              spread: "0",
              repayment_type: "AMORTIZING",
              remaining_months: 36,
            },
          ]
        : [],
      fixed_cost_schedule: [],
      cost_exposures: {
        imported_ingredient_share: "0.25",
        variable_rate_debt_share: "0",
      },
    },
    research_request: {
      run_id: runId,
      tenant_id: "default",
      as_of_date: form.asOf,
      forecast_start: "2026-08-01",
      forecast_end: forecastEnd(horizon),
      store_profile_snapshot_id: `SNP-${form.storeId}`,
      business_type_code: "FNB_CAFE",
      ingredient_categories: ["COFFEE_BEAN"],
      platform_usage: [],
      store_location: {
        address: form.address,
        latitude: coordinates ? Number(coordinates.latitude) : null,
        longitude: coordinates ? Number(coordinates.longitude) : null,
        administrative_area: "서울특별시 강남구",
      },
      administrative_area_codes: ["11680"],
      search_radius_m: 1500,
      official_indicator_snapshot_ids: [],
      event_registry_version: "event_types.v1",
      source_policy_version: "source_tiers.v1",
    },
    official_data_requests: createOfficialDataRequests(form.asOf),
  };
}

export function createWhatIfRequest(values: {
  scenarioName: string;
  revenuePercent: string;
  variablePercent: string;
  fixedPercent: string;
  interestPercentagePoints: string;
}): WhatIfRequest {
  return {
    scenario_name: values.scenarioName,
    revenue_multiplier: 1 + Number(values.revenuePercent) / 100,
    variable_cost_multiplier: 1 + Number(values.variablePercent) / 100,
    fixed_cost_multiplier: 1 + Number(values.fixedPercent) / 100,
    interest_rate_delta: Number(values.interestPercentagePoints) / 100,
  };
}
