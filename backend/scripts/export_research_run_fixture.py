"""Export a recorded research run into a deterministic regression fixture."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from src.contracts.source_document import SourceDocument


def _json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


def _rows(connection: sqlite3.Connection, sql: str, parameters=()) -> list[dict[str, Any]]:
    return [
        {key: _json(value) for key, value in dict(row).items()}
        for row in connection.execute(sql, parameters).fetchall()
    ]


def export_fixture(database: Path, run_id: str) -> dict[str, Any]:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    run = connection.execute(
        "SELECT id, request_json, status, schema_version, registry_version, producer "
        "FROM research_runs WHERE id=?", (run_id,)
    ).fetchone()
    if run is None:
        raise ValueError(f"{run_id} was not found in {database}")
    query_rows = _rows(
        connection,
        "SELECT id, query, metadata_json, status FROM search_queries "
        "WHERE run_id=? ORDER BY created_at, id",
        (run_id,),
    )
    query_ids = [item["id"] for item in query_rows]
    search_results: list[dict[str, Any]] = []
    for query_id in query_ids:
        search_results.extend(_rows(
            connection,
            "SELECT id, query_id, url, rank, metadata_json, status "
            "FROM search_results WHERE query_id=? ORDER BY rank, id",
            (query_id,),
        ))
    revisions = _rows(
        connection,
        "SELECT revision_id, source_id, body_sha256, document_json, status "
        "FROM source_document_revisions WHERE run_id=? ORDER BY created_at, revision_id",
        (run_id,),
    )
    for revision in revisions:
        document = revision["document_json"]
        if isinstance(document, dict):
            normalized = SourceDocument.model_validate(document)
            document = normalized.model_dump(mode="json")
            revision["document_json"] = document
            revision["snapshot_fingerprint"] = normalized.snapshot_fingerprint
            revision["routing_metadata_version"] = normalized.routing_metadata_version
            document.pop("raw_content_uri", None)
    payload = {
        "schema_version": "research_run_regression_fixture.v1",
        "run_id": run_id,
        "recorded_status": run["status"],
        "request": _json(run["request_json"]),
        "run_schema_version": run["schema_version"],
        "registry_version": run["registry_version"],
        "producer": run["producer"],
        "queries": query_rows,
        "ordered_discovery_results": search_results,
        "source_revisions": revisions,
        "extraction_runs": _rows(
            connection,
            "SELECT id, source_revision_id, metadata_json, status "
            "FROM extraction_runs WHERE run_id=? ORDER BY created_at, id",
            (run_id,),
        ),
        "policy_candidates": _rows(
            connection,
            "SELECT policy_candidate_id, policy_json, status "
            "FROM policy_candidates WHERE run_id=? ORDER BY policy_candidate_id",
            (run_id,),
        ),
        "policy_validation_stages": _rows(
            connection,
            "SELECT id, policy_candidate_id, log_json, status "
            "FROM policy_validation_logs WHERE run_id=? ORDER BY created_at, id",
            (run_id,),
        ),
        "provider_diagnostics": _rows(
            connection,
            "SELECT id, record_json, status FROM model_call_records "
            "WHERE run_id=? ORDER BY created_at, id",
            (run_id,),
        ),
        "event_validation_stages": _rows(
            connection,
            "SELECT id, candidate_id, from_state, to_state, failure_code, detail, status "
            "FROM validation_logs WHERE run_id=? ORDER BY created_at, id",
            (run_id,),
        ),
    }
    connection.close()
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    payload["fixture_sha256"] = hashlib.sha256(canonical).hexdigest()
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    payload = export_fixture(arguments.database, arguments.run_id)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    main()

