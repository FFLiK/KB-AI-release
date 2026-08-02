from __future__ import annotations

import calendar,hashlib,math
from datetime import date
from decimal import Decimal
from pathlib import Path
import yaml

from src.contracts.canonical_event import CanonicalEvent
from src.contracts.store import StoreProfile
from src.contracts.store_signal import ScenarioAdjustment,StoreSignal
from src.registries.event_registry import default_registry
from src.signals.evidence_score import calculate_evidence_score
from src.signals.exposure_score import calculate_schedule_overlap
from src.validation.geo_validator import evaluate_geo_exposure


class ResearchSignalBuilder:
    def __init__(self):
        self.registry=default_registry()
        with Path(__file__).parents[1].joinpath("registries/coefficients.v1.yaml").open(encoding="utf-8") as f: self.coefficients=yaml.safe_load(f)
    def build(self,events:list[CanonicalEvent],store:StoreProfile,forecast_start:date,months:int)->tuple[list[StoreSignal],dict[str,ScenarioAdjustment]]:
        signals=[]
        for event in events:
            if event.validation_status!="ACCEPTED" or not event.signal_enabled: continue
            cfg=self.registry.get(str(event.event_type)); severity=Decimal(str(cfg["severity"])); evidence=Decimal(str(calculate_evidence_score(event.source_tier)))
            affected={str(item) for item in event.affected_industry_codes}
            industry_relevance = Decimal("1") if store.business_type_code in affected else (
                Decimal("0.7") if store.business_type_code.startswith("FNB") and any(item.startswith("FNB") for item in affected)
                else Decimal("0.3")
            )
            event_hours=event.attributes.get("operating_hours") if isinstance(event.attributes,dict) else None
            store_hours=next((periods[0] for periods in (store.opening_hours or {}).values() if periods),None)
            for offset in range(months):
                month_index=forecast_start.month-1+offset; year=forecast_start.year+month_index//12; month=month_index%12+1
                month_start=date(year,month,1); month_end=date(year,month,calendar.monthrange(year,month)[1])
                overlap_start=max(month_start,event.start_date); overlap_end=min(month_end,event.end_date or month_end)
                overlap=Decimal("0") if overlap_start>overlap_end else Decimal((overlap_end-overlap_start).days+1)/Decimal((month_end-month_start).days+1)
                if event.domain=="LOCAL":
                    geo,_=evaluate_geo_exposure(store.latitude,store.longitude,event.location.latitude,event.location.longitude)
                    geo=Decimal(str(geo))
                else: geo=Decimal("1")
                schedule_overlap=Decimal(str(calculate_schedule_overlap(event_hours,store_hours)))
                months_since=max(0,(year-event.start_date.year)*12+month-event.start_date.month)
                time_decay=Decimal("1")/(Decimal("1")+Decimal("0.15")*Decimal(months_since))
                exposure=geo*overlap*industry_relevance*schedule_overlap
                for impact in event.impacts:
                    direction=1 if str(impact.direction)=="INCREASE" else -1 if str(impact.direction)=="DECREASE" else 0
                    financial_exposure = Decimal("1")
                    if str(impact.axis).split(".")[-1] == "INTEREST_COST":
                        financial_exposure = Decimal("1") if (
                            store.cost_exposures.variable_rate_debt_share > 0
                            and any(loan.rate_type == "VARIABLE" for loan in store.loans)
                        ) else Decimal("0")
                    raw=Decimal(direction)*evidence*exposure*severity*time_decay*financial_exposure
                    key=f"{event.event_id}|{store.store_id}|{year:04d}-{month:02d}|{impact.axis}"
                    signals.append(StoreSignal(signal_id="SIG-"+hashlib.sha256(key.encode()).hexdigest()[:20].upper(),event_id=event.event_id,source_ids=event.source_ids,store_id=store.store_id,month=f"{year:04d}-{month:02d}",impact_axis=str(impact.axis),direction=direction,evidence_score=evidence,exposure_score=exposure,severity_score=severity,time_decay=time_decay,raw_signal=raw,coefficient_id=f"COEF-{impact.axis}-FNB-v1",coefficient_status="STRESS_ASSUMPTION",cause_group_id=event.cause_group_id))
        signals=self._dedupe_causes(signals)
        return signals,{name:self._adjust(name,signals) for name in ("BASELINE","LOW_IMPACT","HIGH_IMPACT")}
    def _dedupe_causes(self,signals:list[StoreSignal])->list[StoreSignal]:
        chosen={}
        for signal in signals:
            key=(signal.month,signal.impact_axis,signal.cause_group_id or signal.event_id)
            if key not in chosen or abs(signal.raw_signal)>abs(chosen[key].raw_signal): chosen[key]=signal
        return list(chosen.values())
    def _adjust(self,scenario:str,signals:list[StoreSignal])->ScenarioAdjustment:
        result=ScenarioAdjustment(scenario=scenario,signal_ids=[s.signal_id for s in signals],event_ids=sorted({s.event_id for s in signals}),source_ids=sorted({x for s in signals for x in s.source_ids}))
        if scenario=="BASELINE": return result
        coeff=self.coefficients["scenarios"][scenario.lower()]; shocks={}
        for signal in signals:
            axis=signal.impact_axis; shocks[axis]=shocks.get(axis,Decimal("0"))+signal.raw_signal*Decimal(str(coeff[axis]["beta"]))
        def multiplier(axis):
            rule=coeff[axis]; shock=max(Decimal(str(rule["lower_bound"])),min(Decimal(str(rule["upper_bound"])),shocks.get(axis,Decimal("0"))))
            return Decimal(str(round(math.exp(float(shock)),6)))
        revenue_shock=shocks.get("REVENUE_DEMAND",Decimal("0"))-shocks.get("COMPETITION",Decimal("0"))-abs(shocks.get("UNCERTAINTY",Decimal("0")))
        rrule=coeff["REVENUE_DEMAND"]; revenue_shock=max(Decimal(str(rrule["lower_bound"])),min(Decimal(str(rrule["upper_bound"])),revenue_shock))
        result.revenue_multiplier=Decimal(str(round(math.exp(float(revenue_shock)),6)))
        result.variable_cost_multiplier=multiplier("INGREDIENT_COST")*multiplier("PLATFORM_COST")
        result.fixed_cost_multiplier=multiplier("OPERATING_COST")
        result.interest_rate_delta=max(Decimal("0"),shocks.get("INTEREST_COST",Decimal("0")))
        return result
