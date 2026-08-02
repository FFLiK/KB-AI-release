from __future__ import annotations

from decimal import Decimal
from pydantic import Field
from src.contracts.research import StrictModel


class StoreSignal(StrictModel):
    signal_id:str; event_id:str; source_ids:list[str]; store_id:str; month:str; impact_axis:str; direction:int=Field(ge=-1,le=1)
    evidence_score:Decimal=Field(ge=0,le=1); exposure_score:Decimal=Field(ge=0,le=1); severity_score:Decimal=Field(ge=0,le=1); time_decay:Decimal=Field(ge=0,le=1)
    raw_signal:Decimal; coefficient_id:str; coefficient_status:str; cause_group_id:str|None=None; calculation_version:str="store_signal.v1"


class ScenarioAdjustment(StrictModel):
    scenario:str
    revenue_multiplier:Decimal=Decimal("1")
    variable_cost_multiplier:Decimal=Decimal("1")
    fixed_cost_multiplier:Decimal=Decimal("1")
    interest_rate_delta:Decimal=Decimal("0")
    signal_ids:list[str]=Field(default_factory=list)
    event_ids:list[str]=Field(default_factory=list)
    source_ids:list[str]=Field(default_factory=list)
    coefficient_version:str="coefficients.v1"
