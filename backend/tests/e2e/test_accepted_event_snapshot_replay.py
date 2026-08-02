import hashlib
import json
from decimal import Decimal

import pytest

from src.signals.monthly_builder import MonthlySignalBuilder
from src.storage import Database, EventRepository
from src.validation.research_validator import ResearchEventValidator
from tests.e2e.support import load_store, research_request
from tests.research_fixtures import candidate, source_document


pytestmark = pytest.mark.e2e


def test_persisted_accepted_event_snapshot_replays_without_an_llm(tmp_path) -> None:
    store = load_store().model_copy(update={
        "latitude": Decimal("37.5"),
        "longitude": Decimal("127.0"),
    })
    request = research_request(store, run_id="RES-TEST")
    document = source_document()
    extracted = candidate(document)
    outcome = ResearchEventValidator().validate(extracted, {document.source_id: document}, request)
    assert outcome.status == "ACCEPTED" and outcome.event is not None

    database = Database(f"sqlite:///{(tmp_path / 'accepted-event.db').as_posix()}")
    database.migrate()
    repository = EventRepository(database)
    repository.save_candidate(extracted)
    repository.save_canonical(outcome.event)
    restored = repository.list_events(request.run_id, accepted_only=True)
    assert len(restored) == 1

    replay_hashes = set()
    replay_values = set()
    for _ in range(10):
        signals, adjustments = MonthlySignalBuilder().build(restored, store, request.forecast_start, 6)
        payload = {
            "event": [item.model_dump(mode="json") for item in restored],
            "signals": [item.model_dump(mode="json") for item in signals],
            "adjustments": {
                key: value.model_dump(mode="json") for key, value in sorted(adjustments.items())
            },
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        replay_hashes.add(hashlib.sha256(encoded.encode()).hexdigest())
        replay_values.add(tuple(
            (item.month, str(item.revenue_multiplier), str(item.variable_cost_multiplier))
            for item in adjustments["HIGH_IMPACT"].months
        ))

    assert len(replay_hashes) == len(replay_values) == 1
    assert all(signal.event_id == restored[0].event_id for signal in signals)
    assert adjustments["HIGH_IMPACT"].source_ids == restored[0].source_ids
