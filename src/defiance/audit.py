"""Anonymous runtime audit storage for accepted Defiance questions."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from .answer import AnswerResult


AUDIT_SCHEMA_VERSION = 1
AUDIT_SCHEMA = """
CREATE TABLE ask_requests (
    request_id TEXT PRIMARY KEY,
    submitted_at_utc TEXT NOT NULL,
    question TEXT NOT NULL,
    answer_status TEXT NOT NULL CHECK (
        answer_status IN (
            'answered', 'unknown_entity', 'ambiguous_entity', 'unsupported',
            'unavailable', 'no_evidence', 'off_topic'
        )
    ),
    routed_intent TEXT,
    answer_text TEXT NOT NULL,
    failure_reason TEXT,
    elapsed_ms INTEGER NOT NULL CHECK (elapsed_ms >= 0),
    CHECK (
        (answer_status = 'answered' AND failure_reason IS NULL)
        OR (answer_status != 'answered' AND failure_reason IS NOT NULL)
    )
);

CREATE TABLE ask_evidence (
    request_id TEXT NOT NULL REFERENCES ask_requests(request_id) ON DELETE CASCADE,
    evidence_order INTEGER NOT NULL CHECK (evidence_order >= 0),
    label TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_locator TEXT NOT NULL,
    original_url TEXT NOT NULL,
    PRIMARY KEY (request_id, evidence_order)
);
"""


class AuditError(RuntimeError):
    """Raised when the runtime audit database cannot be used safely."""


def _connect(database_path: Path, *, create: bool) -> sqlite3.Connection:
    try:
        if create:
            database_path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(database_path, timeout=5.0)
        else:
            connection = sqlite3.connect(
                f"file:{database_path}?mode=rw",
                uri=True,
                timeout=5.0,
            )
    except (OSError, sqlite3.Error) as exc:
        raise AuditError("cannot open runtime audit database") from exc
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def _require_current_schema(connection: sqlite3.Connection) -> None:
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if version != AUDIT_SCHEMA_VERSION:
        raise AuditError("runtime audit database has an unsupported schema version")
    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_schema WHERE type = 'table'"
        )
    }
    if not {"ask_requests", "ask_evidence"}.issubset(tables):
        raise AuditError("runtime audit database schema is incomplete")


def initialize_audit_database(database_path: Path) -> None:
    """Create the V1 audit schema once and reject unknown versions."""
    connection = _connect(database_path, create=True)
    try:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version == 0:
            with connection:
                connection.executescript(AUDIT_SCHEMA)
                connection.execute(f"PRAGMA user_version = {AUDIT_SCHEMA_VERSION}")
        _require_current_schema(connection)
    except sqlite3.Error as exc:
        raise AuditError("cannot initialize runtime audit database") from exc
    finally:
        connection.close()


def record_answer(
    database_path: Path,
    *,
    request_id: str,
    submitted_at_utc: str,
    question: str,
    result: AnswerResult,
    elapsed_ms: int,
) -> None:
    """Persist one accepted question and its exact deterministic result."""
    connection = _connect(database_path, create=False)
    try:
        _require_current_schema(connection)
        with connection:
            connection.execute(
                """
                INSERT INTO ask_requests(
                    request_id, submitted_at_utc, question, answer_status,
                    routed_intent, answer_text, failure_reason, elapsed_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    submitted_at_utc,
                    question,
                    result.status,
                    result.intent,
                    result.text,
                    result.failure_reason,
                    elapsed_ms,
                ),
            )
            connection.executemany(
                """
                INSERT INTO ask_evidence(
                    request_id, evidence_order, label, source_id,
                    source_locator, original_url
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        request_id,
                        order,
                        evidence.label,
                        evidence.source_id,
                        evidence.source_locator,
                        evidence.original_url,
                    )
                    for order, evidence in enumerate(result.evidence)
                ),
            )
    except (AuditError, sqlite3.Error) as exc:
        if isinstance(exc, AuditError):
            raise
        raise AuditError("cannot record runtime audit result") from exc
    finally:
        connection.close()


def check_audit_database(database_path: Path) -> None:
    """Verify that the existing audit database can accept a short transaction."""
    connection = _connect(database_path, create=False)
    try:
        _require_current_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        connection.rollback()
    except (AuditError, sqlite3.Error) as exc:
        if isinstance(exc, AuditError):
            raise
        raise AuditError("runtime audit database is not writable") from exc
    finally:
        connection.close()
