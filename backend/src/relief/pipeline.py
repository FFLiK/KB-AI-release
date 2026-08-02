"""Deterministic eligibility, benefit simulation and policy ranking."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from src.contracts.analysis import (
    PolicyEligibilityResult,
    PolicyResultBundle,
    PolicyStageCounts,
    PolicySearchContext,
    RankedPolicyOption,
)
from src.contracts.financial import FinancialScenarioResult
from src.contracts.forecast import BaselineForecastBundle
from src.contracts.official import OfficialFeatureSet
from src.contracts.loan import Loan
from src.contracts.policy_candidate import PolicyCandidate
from src.contracts.scenario import ScenarioAdjustmentV2
from src.contracts.store import StoreProfile
from src.finance.monthly_scenario import run_monthly_financial_scenario
from src.relief.benefit_simulator import ReliefBenefitComparison
from src.relief.eligibility_rules import evaluate_policy_eligibility_detailed
from src.relief.policy_schema import PolicySchema


def build_policy_search_context(
    store: StoreProfile,
    baseline_result: FinancialScenarioResult,
    region_codes: list[str],
) -> PolicySearchContext:
    ending_values = [item.ending_cash_krw for item in baseline_result.monthly_cash_flows]
    minimum_ending = min(ending_values) if ending_values else store.current_cash_krw
    required = max(Decimal("0"), store.minimum_operating_cash_krw - minimum_ending)
    return PolicySearchContext(
        cash_burn_date=baseline_result.cash_burn_result.cash_burn_date,
        liquidity_risk_date=baseline_result.cash_burn_result.liquidity_risk_date,
        required_funding_krw=required,
        business_type_code=store.business_type_code,
        region_codes=region_codes,
        purposes=["WORKING_CAPITAL", "INTEREST_REDUCTION"] if store.loans else ["WORKING_CAPITAL"],
    )


def _policy_schema(candidate: PolicyCandidate) -> PolicySchema:
    discount_points = candidate.interest_terms.rate_discount_percentage_points or Decimal("0")
    return PolicySchema(
        policy_id=candidate.policy_candidate_id,
        name=candidate.name,
        provider=candidate.provider_raw,
        purpose=candidate.purpose,
        region_codes=candidate.region_codes,
        industry_inclusions=candidate.industry_inclusions_raw,
        industry_exclusions=candidate.industry_exclusions_raw,
        limit_krw=candidate.limit_krw or Decimal("0"),
        interest_rate_discount=discount_points / Decimal("100"),
        principal_grace_months=candidate.repayment_terms.principal_grace_months or 0,
        application_start=str(candidate.application_start) if candidate.application_start else None,
        application_end=str(candidate.application_end) if candidate.application_end else None,
        budget_status=candidate.budget_status,
        validation_status=candidate.validation_status,
        eligibility_conditions=candidate.eligibility_conditions,
    )


def _days(value: str | None) -> date | None:
    if not value or value == "NONE":
        return None
    return date.fromisoformat(value[:10])


def _apply_funding_terms(
    modified: StoreProfile,
    candidate: PolicyCandidate,
    policy: PolicySchema,
    context: PolicySearchContext,
) -> tuple[list[str], dict[str, int]]:
    notes: list[str] = []
    grace_by_loan: dict[str, int] = {}
    funding_amount = min(policy.limit_krw, context.required_funding_krw)
    policy_type = str(candidate.policy_type)

    if policy_type == "GRANT" and funding_amount > 0:
        modified.current_cash_krw += funding_amount
        notes.append("Grant cash inflow capped at the calculated funding gap")
    elif policy_type == "LOAN_SUPPORT" and funding_amount > 0:
        annual_rate = candidate.interest_terms.annual_rate_percent
        maturity = candidate.repayment_terms.maturity_months
        repayment = candidate.repayment_terms.repayment_method
        supported_methods = {"BULLET", "EQUAL_PRINCIPAL", "AMORTIZING"}
        if annual_rate is not None and maturity and repayment in supported_methods:
            policy_loan_id = f"POLICY-{policy.policy_id}"
            modified.current_cash_krw += funding_amount
            modified.loans.append(Loan(
                loan_id=policy_loan_id,
                principal_balance_krw=funding_amount,
                annual_interest_rate=annual_rate / Decimal("100"),
                rate_type="FIXED",
                repayment_type=repayment,
                remaining_months=maturity,
            ))
            grace_by_loan[policy_loan_id] = policy.principal_grace_months
            notes.append(
                "Loan draw capped at the funding gap; explicit rate, maturity and repayment terms applied"
            )
        else:
            notes.append("Loan funding excluded because rate, maturity or repayment terms were incomplete")

    if policy_type == "REPAYMENT_DEFERRAL":
        grace_by_loan.update({loan.loan_id: policy.principal_grace_months for loan in modified.loans})
    return notes, grace_by_loan


class EligibilityAndBenefitPipeline:
    def run(
        self,
        store: StoreProfile,
        as_of_date: date,
        candidates: list[PolicyCandidate],
        context: PolicySearchContext,
        baseline: BaselineForecastBundle,
        baseline_adjustment: ScenarioAdjustmentV2,
        baseline_result: FinancialScenarioResult,
        official_features: OfficialFeatureSet | None = None,
    ) -> PolicyResultBundle:
        eligibility: list[PolicyEligibilityResult] = []
        benefits: list[ReliefBenefitComparison] = []
        scored: list[tuple[Decimal, str, list[str]]] = []
        validation_results = []
        region = context.region_codes[0] if context.region_codes else ""
        for candidate in sorted(candidates, key=lambda item: item.policy_candidate_id):
            validation_results.append({
                "policy_id": candidate.policy_candidate_id,
                "status": candidate.validation_status,
                "source_ids": candidate.source_ids,
                "failure_codes": candidate.validation_failure_codes,
                "validation_notes": candidate.validation_notes,
                "application_status": candidate.application_status,
                "recommendation_failure_codes": candidate.recommendation_failure_codes,
            })
            if candidate.validation_status == "CLOSED":
                eligibility.append(PolicyEligibilityResult(
                    policy_id=candidate.policy_candidate_id,
                    status="CLOSED",
                    reason="The official program is closed and remains visible for traceability",
                    source_ids=candidate.source_ids,
                ))
                continue
            if candidate.validation_status != "VALIDATED":
                eligibility.append(PolicyEligibilityResult(
                    policy_id=candidate.policy_candidate_id,
                    status="NOT_VALIDATED",
                    reason=(
                        "Official evidence validation failed: "
                        + ", ".join(candidate.validation_failure_codes)
                    ),
                    source_ids=candidate.source_ids,
                ))
                continue
            if candidate.application_status == "BUDGET_EXHAUSTED":
                eligibility.append(PolicyEligibilityResult(
                    policy_id=candidate.policy_candidate_id,
                    status="BUDGET_EXHAUSTED",
                    reason="The official budget is exhausted; the program remains visible",
                    source_ids=candidate.source_ids,
                ))
                continue
            if candidate.application_status == "SCHEDULED":
                eligibility.append(PolicyEligibilityResult(
                    policy_id=candidate.policy_candidate_id,
                    status="SCHEDULED",
                    reason="The official application period has not started",
                    source_ids=candidate.source_ids,
                ))
                continue
            if candidate.application_status == "STATUS_UNCONFIRMED":
                eligibility.append(PolicyEligibilityResult(
                    policy_id=candidate.policy_candidate_id,
                    status="STATUS_UNCONFIRMED",
                    reason="Current application status is not confirmed by official evidence",
                    source_ids=candidate.source_ids,
                ))
                continue
            if candidate.budget_status.upper() in {"UNKNOWN", "BUDGET_UNKNOWN"}:
                eligibility.append(PolicyEligibilityResult(
                    policy_id=candidate.policy_candidate_id,
                    status="BUDGET_UNKNOWN",
                    reason="Current budget availability is not confirmed by official evidence",
                    source_ids=candidate.source_ids,
                ))
                continue

            policy = _policy_schema(candidate)
            status, reason, condition_logs = evaluate_policy_eligibility_detailed(
                store, policy, region, as_of_date
            )
            validation_results[-1]["eligibility_rule_results"] = condition_logs
            validation_results[-1]["eligibility_rule_status"] = status
            if policy.application_start and as_of_date < date.fromisoformat(policy.application_start):
                status, reason = "NOT_OPEN", "Application period has not started"
            if policy.application_end and as_of_date > date.fromisoformat(policy.application_end):
                status, reason = "CLOSED", "Application period has ended"
            eligibility.append(PolicyEligibilityResult(
                policy_id=policy.policy_id,
                status=status,
                reason=reason,
                source_ids=candidate.source_ids,
            ))
            if status != "ELIGIBLE_ON_DECLARED_RULES":
                continue

            modified = store.model_copy(deep=True)
            simulation_notes, grace_by_loan = _apply_funding_terms(modified, candidate, policy, context)
            for loan in modified.loans:
                loan.annual_interest_rate = max(
                    Decimal("0"), loan.annual_interest_rate - policy.interest_rate_discount
                )
            simulated = run_monthly_financial_scenario(
                modified,
                baseline,
                baseline_adjustment,
                principal_grace_months_by_loan=grace_by_loan,
                official_features=official_features,
            )
            original_interest = sum(item.interest_payment_krw for item in baseline_result.monthly_cash_flows)
            simulated_interest = sum(item.interest_payment_krw for item in simulated.monthly_cash_flows)
            original_burn = _days(baseline_result.cash_burn_result.cash_burn_date)
            simulated_burn = _days(simulated.cash_burn_result.cash_burn_date)
            horizon_end = date.fromisoformat(baseline.monthly_forecasts[-1].month + "-28")
            if original_burn:
                runway_days = ((simulated_burn or horizon_end) - original_burn).days
            else:
                runway_days = 0
            benefit = ReliefBenefitComparison(
                policy_id=policy.policy_id,
                policy_name=policy.name,
                eligibility_status=status,
                original_cash_burn_date=str(original_burn or "NONE"),
                simulated_cash_burn_date=str(simulated_burn or "NONE"),
                runway_extension_days=max(0, runway_days),
                cumulative_interest_savings_krw=max(Decimal("0"), original_interest - simulated_interest),
            )
            benefits.append(benefit)
            score = Decimal("100")
            reasons = ["Declared eligibility rules passed", *simulation_notes]
            if original_burn and (policy.application_start is None or date.fromisoformat(policy.application_start) <= original_burn):
                score += Decimal("20")
                reasons.append("Application can begin before projected cash burn")
            score += min(Decimal("30"), Decimal(benefit.runway_extension_days) / Decimal("3"))
            score += min(Decimal("20"), benefit.cumulative_interest_savings_krw / Decimal("100000"))
            if candidate.guarantee_terms.collateral_required:
                score -= Decimal("10")
                reasons.append("Collateral burden applies")
            if candidate.repayment_terms.principal_grace_months:
                score += min(Decimal("10"), Decimal(candidate.repayment_terms.principal_grace_months))
                reasons.append("Principal grace period available")
            scored.append((score, policy.policy_id, reasons))

        scored.sort(key=lambda item: (-item[0], item[1]))
        ranked = [RankedPolicyOption(policy_id=policy_id, rank=index, score=score, reasons=reasons)
                  for index, (score, policy_id, reasons) in enumerate(scored, start=1)]
        return PolicyResultBundle(
            search_context=context,
            candidates=candidates,
            extracted_candidates=candidates,
            eligible_recommendations=ranked,
            validation_results=validation_results,
            eligibility_results=eligibility,
            benefit_simulations=benefits,
            ranked_options=ranked,
            stage_counts=PolicyStageCounts(
                extracted_candidates=len(candidates),
                validated_policies=sum(item.validation_status == "VALIDATED" for item in candidates),
                closed_policies=sum(item.validation_status == "CLOSED" for item in candidates),
                eligible_policies=sum(item.status == "ELIGIBLE_ON_DECLARED_RULES" for item in eligibility),
                ranked_recommendations=len(ranked),
            ),
            official_confirmation_required=True,
        )
