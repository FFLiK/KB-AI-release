from datetime import date

from src.forecasting.official_event_bridge import apply_official_event_bridge
from tests.test_run_d0dcee2c_94a_remediation import official_bundle, observation, rate_event


def test_missing_official_rate_value_is_recorded_as_ineligible_without_crashing() -> None:
    event = rate_event().model_copy(deep=True)
    event.attributes["official_new_value"] = None
    event.attributes["official_value_unit"] = None
    bundle = official_bundle(observation(date(2026, 6, 30), "2.50", "OBS-JUN"))

    _, decisions = apply_official_event_bridge(bundle, [event])

    assert len(decisions) == 1
    assert decisions[0].status == "INELIGIBLE"
    assert decisions[0].reason_code == "VALUE_OR_UNIT_NOT_EXPLICITLY_EVIDENCED"
