"""Monthly forecast-aware deterministic financial scenario calculation."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.contracts.financial import BEPResult, FinancialScenarioResult, MonthlyCashFlow
from src.contracts.forecast import BaselineForecastBundle
from src.contracts.official import OfficialFeatureSet
from src.contracts.scenario import ScenarioAdjustmentV2
from src.contracts.store import StoreProfile
from src.finance.break_even import calculate_bep
from src.finance.cashflow import calculate_monthly_cashflow, evaluate_cash_burn_and_liquidity_risk
from src.finance.loan import calculate_loan_schedule


def run_monthly_financial_scenario(
    store: StoreProfile,
    baseline: BaselineForecastBundle,
    adjustment: ScenarioAdjustmentV2,
    principal_grace_months: int = 0,
    principal_grace_months_by_loan: dict[str, int] | None = None,
    official_features: OfficialFeatureSet | None = None,
) -> FinancialScenarioResult:
    if not baseline.monthly_forecasts:
        raise ValueError("INSUFFICIENT_DATA: baseline monthly forecasts are required")
    if not store.monthly_history:
        raise ValueError("INSUFFICIENT_DATA: cost history is required for financial calculation")
    if len(adjustment.months) != len(baseline.monthly_forecasts):
        raise ValueError("adjustment month count must match baseline forecast horizon")
    if [item.month for item in adjustment.months] != [item.month for item in baseline.monthly_forecasts]:
        raise ValueError("adjustment months must align with baseline forecast months")

    last = sorted(store.monthly_history, key=lambda item: item.month)[-1]
    historical_revenue = last.revenue_krw
    ingredient_ratio = last.variable_costs.ingredients_krw / historical_revenue if historical_revenue > 0 else Decimal("0")
    platform_ratio = last.variable_costs.platform_fee_krw / historical_revenue if historical_revenue > 0 else Decimal("0")
    payment_ratio = last.variable_costs.payment_fee_krw / historical_revenue if historical_revenue > 0 else Decimal("0")
    other_variable_ratio = platform_ratio + payment_ratio
    base_fixed_by_category = {
        "rent": last.fixed_costs.rent_krw,
        "labor": last.fixed_costs.labor_krw,
        "utilities": last.fixed_costs.utilities_krw,
        "other": last.fixed_costs.other_krw,
    }

    def combined_rate_delta(item):
        has_variable_debt = (
            store.cost_exposures.variable_rate_debt_share > 0
            and any(loan.rate_type == "VARIABLE" for loan in store.loans)
        )
        if not has_variable_debt:
            return Decimal("0")
        feature_delta = official_features.for_month(item.month).interest_rate_delta if official_features else Decimal("0")
        return item.interest_rate_delta + feature_delta

    rate_deltas = sorted({combined_rate_delta(item) for item in adjustment.months})
    loan_schedules = {
        delta: [
            calculate_loan_schedule(
                loan,
                len(adjustment.months),
                rate_change_delta=delta,
                principal_grace_months=(principal_grace_months_by_loan or {}).get(
                    loan.loan_id, principal_grace_months
                ),
                forecast_start=date.fromisoformat(baseline.monthly_forecasts[0].month + "-01"),
            )[0]
            for loan in store.loans
        ]
        for delta in rate_deltas
    }

    cash = store.current_cash_krw
    cash_flows: list[MonthlyCashFlow] = []
    bep_results: list[BEPResult] = []
    for index, (forecast, monthly_adjustment) in enumerate(zip(baseline.monthly_forecasts, adjustment.months), start=1):
        revenue = forecast.point * monthly_adjustment.revenue_multiplier
        official_month = official_features.for_month(forecast.month) if official_features else None
        if official_month:
            imported_share = store.cost_exposures.imported_ingredient_share
            domestic_share = Decimal("1") - imported_share
            ingredient_multiplier = (
                domestic_share * official_month.domestic_ingredient_cost_multiplier
                + imported_share * official_month.imported_ingredient_cost_multiplier
            )
        else:
            ingredient_multiplier = Decimal("1")
        ingredient_cost = revenue * ingredient_ratio * ingredient_multiplier
        other_variable_cost = revenue * other_variable_ratio
        variable_cost = (ingredient_cost + other_variable_cost) * monthly_adjustment.variable_cost_multiplier
        fixed_for_month = dict(base_fixed_by_category)
        for entry in store.fixed_cost_schedule:
            if entry.month == forecast.month:
                fixed_for_month[entry.category] = entry.amount_krw
        fixed_cost = sum(fixed_for_month.values(), Decimal("0")) * monthly_adjustment.fixed_cost_multiplier
        interest = Decimal("0")
        principal = Decimal("0")
        for schedule in loan_schedules[combined_rate_delta(monthly_adjustment)]:
            if len(schedule) >= index:
                interest += schedule[index - 1].interest_payment_krw
                principal += schedule[index - 1].principal_payment_krw
        bep_results.append(calculate_bep(
            month_index=index,
            revenue_forecast_krw=revenue,
            total_variable_cost_krw=variable_cost,
            operating_fixed_cost_krw=fixed_cost,
            interest_expense_krw=interest,
            principal_payment_krw=principal,
            tax_cash_outflow_krw=last.tax_cash_outflow_krw,
            capital_expenditure_krw=last.capital_expenditure_krw,
        ))
        cash_flow = calculate_monthly_cashflow(
            month_index=index,
            month_str=forecast.month,
            beginning_cash_krw=cash,
            revenue_cash_krw=revenue,
            variable_costs_cash_krw=variable_cost,
            ingredient_costs_cash_krw=ingredient_cost * monthly_adjustment.variable_cost_multiplier,
            other_variable_costs_cash_krw=other_variable_cost * monthly_adjustment.variable_cost_multiplier,
            fixed_costs_cash_krw=fixed_cost,
            interest_payment_krw=interest,
            principal_payment_krw=principal,
            tax_cash_outflow_krw=last.tax_cash_outflow_krw,
            capital_expenditure_krw=last.capital_expenditure_krw,
        )
        cash_flows.append(cash_flow)
        cash = cash_flow.ending_cash_krw

    event_ids = sorted({event_id for item in adjustment.months for event_id in item.event_ids})
    signal_ids = sorted({signal_id for item in adjustment.months for signal_id in item.signal_ids})
    official_observation_ids = sorted({
        observation_id for feature in (official_features.months if official_features else [])
        for observation_id in feature.source_observation_ids
    })
    return FinancialScenarioResult(
        scenario_name=adjustment.scenario,
        monthly_cash_flows=cash_flows,
        bep_results=bep_results,
        cash_burn_result=evaluate_cash_burn_and_liquidity_risk(cash_flows, store.minimum_operating_cash_krw),
        metadata={
            "scenario_id": f"SCN-{baseline.forecast_id}-{adjustment.scenario}",
            "forecast_id": baseline.forecast_id,
            "adjustment_id": adjustment.adjustment_id,
            "event_ids": ",".join(event_ids),
            "signal_ids": ",".join(signal_ids),
            "source_ids": ",".join(adjustment.source_ids),
            "coefficient_version": adjustment.coefficient_version,
            "calculation_version": "financial_calculation.v2",
            "official_feature_set_id": official_features.feature_set_id if official_features else "NONE",
            "official_observation_ids": ",".join(official_observation_ids),
            "official_source_snapshot_id": official_features.source_snapshot_id if official_features and official_features.source_snapshot_id else "NONE",
            "fixed_cost_schedule_entries": str(len(store.fixed_cost_schedule)),
        },
    )

