from __future__ import annotations

from pathlib import Path

from sqlalchemy import MetaData, Table, create_engine, inspect, select, text
from sqlalchemy.engine import Engine

from src.contracts.source_document import SourceDocument
from src.storage.schema import metadata


class Database:
    """SQLAlchemy store supporting SQLite development and PostgreSQL production URLs."""

    def __init__(self, url: str = "sqlite:///./data/research.db"):
        self.url = url
        if url.startswith("sqlite:///"):
            path = Path(url.removeprefix("sqlite:///"))
            if str(path) != ":memory:":
                path.parent.mkdir(parents=True, exist_ok=True)
        connect_args = {}
        if url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
            connect_args["timeout"] = 30
        self.engine: Engine = create_engine(url, future=True, connect_args=connect_args)
        if url.startswith("sqlite"):
            self._enable_sqlite_wal()

    def _enable_sqlite_wal(self) -> None:
        """Enable WAL mode for SQLite to prevent 'database is locked' during concurrent operations."""
        try:
            with self.engine.connect() as conn:
                conn.execute(text("PRAGMA journal_mode=WAL;"))
                conn.execute(text("PRAGMA synchronous=NORMAL;"))
        except Exception:
            pass

    def create_schema_for_development(self) -> None:
        """Create tables only for local SQLite/tests; production uses Alembic."""
        if not self.url.startswith("sqlite"):
            raise RuntimeError("create_all is restricted to SQLite development databases")
        metadata.create_all(self.engine)
        self._upgrade_legacy_sqlite_columns()

    def _upgrade_legacy_sqlite_columns(self) -> None:
        """Apply additive compatibility upgrades for pre-Alembic local databases.

        ``create_all`` does not add columns to existing SQLite tables. Production
        databases receive the equivalent change through Alembic; this keeps a
        developer's existing ``research.db`` usable after a schema addition.
        """
        if not self.url.startswith("sqlite"):
            return
        policy_columns = {
            column["name"]
            for column in inspect(self.engine).get_columns("policy_candidates")
        }
        if "updated_at" not in policy_columns:
            with self.engine.begin() as conn:
                conn.execute(text("ALTER TABLE policy_candidates ADD COLUMN updated_at DATETIME"))
                conn.execute(text(
                    "UPDATE policy_candidates SET updated_at = created_at "
                    "WHERE updated_at IS NULL"
                ))
        self._upgrade_source_snapshot_identity()

    def _upgrade_source_snapshot_identity(self) -> None:
        """Rebuild the legacy body-unique SQLite table without losing history."""
        inspector = inspect(self.engine)
        table_name = "source_document_revisions"
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        unique_names = {
            item["name"] for item in inspector.get_unique_constraints(table_name)
        }
        if (
            "snapshot_fingerprint" in columns
            and "uq_source_body_hash" not in unique_names
        ):
            return

        with self.engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
            conn.commit()
            try:
                legacy = Table(table_name, MetaData(), autoload_with=conn)
                rows = list(conn.execute(select(legacy)).mappings())
                conn.commit()
                with conn.begin():
                    conn.exec_driver_sql("DROP TABLE IF EXISTS source_document_revisions_v2")
                    conn.exec_driver_sql(
                        """
                        CREATE TABLE source_document_revisions_v2 (
                            revision_id VARCHAR(64) NOT NULL PRIMARY KEY,
                            source_id VARCHAR(64) NOT NULL,
                            body_sha256 VARCHAR(64) NOT NULL,
                            snapshot_fingerprint VARCHAR(64) NOT NULL,
                            document_json JSON NOT NULL,
                            run_id VARCHAR(64),
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            schema_version VARCHAR(64) NOT NULL,
                            registry_version VARCHAR(64) NOT NULL,
                            producer VARCHAR(128) NOT NULL,
                            status VARCHAR(64) NOT NULL,
                            FOREIGN KEY(source_id) REFERENCES source_documents (source_id),
                            CONSTRAINT uq_source_snapshot_fingerprint
                                UNIQUE (source_id, snapshot_fingerprint)
                        )
                        """
                    )
                    upgraded = Table(
                        "source_document_revisions_v2", MetaData(), autoload_with=conn
                    )
                    for row in rows:
                        values = dict(row)
                        document = SourceDocument.model_validate(values["document_json"])
                        values["snapshot_fingerprint"] = document.snapshot_fingerprint
                        values["document_json"] = document.model_dump(mode="json")
                        conn.execute(upgraded.insert().values(**values))
                    conn.exec_driver_sql("DROP TABLE source_document_revisions")
                    conn.exec_driver_sql(
                        "ALTER TABLE source_document_revisions_v2 "
                        "RENAME TO source_document_revisions"
                    )
                    conn.exec_driver_sql(
                        "CREATE INDEX ix_source_document_revisions_run_id "
                        "ON source_document_revisions (run_id)"
                    )
            finally:
                conn.exec_driver_sql("PRAGMA foreign_keys=ON")

                conn.commit()
    def validate_schema(self) -> None:
        present = set(inspect(self.engine).get_table_names())
        missing = set(metadata.tables) - present
        if missing:
            raise RuntimeError(f"Database migrations are not current; missing tables: {sorted(missing)}")

    def initialize_schema(self, mode: str = "auto") -> None:
        selected = mode.lower()
        if selected == "auto":
            selected = "create" if self.url.startswith("sqlite") else "validate"
        if selected == "create":
            self.create_schema_for_development()
        elif selected in {"validate", "alembic"}:
            self.validate_schema()
        else:
            raise ValueError(f"Unsupported DB_SCHEMA_MODE: {mode}")

    def migrate(self) -> None:
        """Backward-compatible test helper. Application startup uses initialize_schema."""
        self.create_schema_for_development()

    def dispose(self) -> None:
        self.engine.dispose()
