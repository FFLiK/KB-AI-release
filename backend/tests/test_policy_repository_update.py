from decimal import Decimal

from sqlalchemy import select

from src.contracts.event_candidate import EvidenceRef
from src.contracts.policy_candidate import PolicyCandidate
from src.storage import Database, PolicyRepository
from src.storage.schema import policy_candidates


def _policy(*, run_id: str, status: str) -> PolicyCandidate:
    quote = "Gangnam small-business loan support is available."
    return PolicyCandidate(
        policy_candidate_id="POL-RECURRING-TEST",
        identity_fingerprint="a" * 64,
        research_run_id=run_id,
        policy_type="LOAN_SUPPORT",
        name="Gangnam small-business loan support",
        provider_raw="Gangnam District Office",
        limit_krw=Decimal("10000000"),
        source_ids=["SRC-POLICY-TEST"],
        evidence=[EvidenceRef(
            evidence_id=f"EVI-{run_id}",
            source_id="SRC-POLICY-TEST",
            source_revision_id="REV-POLICY-TEST",
            field_paths=["name", "limit_krw"],
            quote=quote,
            start_offset=0,
            end_offset=len(quote),
        )],
        validation_status=status,
    )


def test_existing_policy_is_updated_across_runs_with_timestamp(tmp_path):
    database = Database(f"sqlite:///{(tmp_path / 'policy-update.db').as_posix()}")
    database.migrate()
    repository = PolicyRepository(database)

    repository.save(_policy(run_id="RUN-ONE", status="EXTRACTED"))
    with database.engine.connect() as conn:
        first = conn.execute(select(
            policy_candidates.c.updated_at,
            policy_candidates.c.policy_json,
        )).one()
    assert first.updated_at is not None

    repository.save(_policy(run_id="RUN-TWO", status="VALIDATED"))
    with database.engine.connect() as conn:
        stored = conn.execute(select(
            policy_candidates.c.updated_at,
            policy_candidates.c.policy_json,
            policy_candidates.c.status,
        )).one()

    assert stored.updated_at >= first.updated_at
    assert stored.policy_json["research_run_id"] == "RUN-TWO"
    assert stored.status == "VALIDATED"
