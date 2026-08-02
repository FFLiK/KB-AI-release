import pytest

from tests.e2e.support import build_orchestrator, load_store, official_requests, research_request


pytestmark = pytest.mark.e2e


def test_ten_fresh_replays_and_idempotent_recovery_are_identical(tmp_path) -> None:
    store = load_store()
    request = research_request(store, run_id="OFFLINE-REPLAY-HASH")
    fingerprints = []

    for replay_index in range(10):
        orchestrator, _ = build_orchestrator(tmp_path / f"replay-{replay_index}")
        first = orchestrator.run(
            store,
            request,
            official_requests(),
            idempotency_key="OFFLINE-REPLAY-STABLE-IDEMPOTENCY",
        ).result
        repeated = orchestrator.run(
            store,
            request,
            official_requests(),
            idempotency_key="OFFLINE-REPLAY-STABLE-IDEMPOTENCY",
        ).result
        assert repeated.result_id == first.result_id
        assert repeated.deterministic_hash == first.deterministic_hash
        fingerprints.append((
            first.deterministic_hash,
            first.scenarios,
            first.traceability.source_ids,
            first.traceability.official_observation_ids,
            first.versions,
        ))

    assert all(item == fingerprints[0] for item in fingerprints[1:])
