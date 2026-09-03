"""Fail-closed production startup checks for the Railway deployment."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import sqlite3
import stat
import sys

from .audit import AuditError, initialize_audit_database
from .corpus_db import validate_database
from .db import ValidationError


EXPECTED_VOLUME_MOUNT = Path("/data")
EXPECTED_CORPUS_SHA256 = (
    "295f6fb5325f8b82be2d8a12d2ae7106f70560824aca4394c483850d9b6c3245"
)


class ProductionConfigurationError(RuntimeError):
    """Raised when production cannot start without violating its guarantees."""


@dataclass(frozen=True)
class ProductionPaths:
    """Validated production database locations."""

    volume: Path
    corpus: Path
    audit: Path


def _required_environment(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name, "").strip()
    if not value:
        raise ProductionConfigurationError("required production configuration is missing")
    return value


def _resolve_inside_volume(raw_path: str, volume: Path) -> Path:
    configured_path = Path(raw_path)
    if not configured_path.is_absolute():
        raise ProductionConfigurationError("database path must be absolute")
    path = configured_path.resolve(strict=False)
    try:
        path.relative_to(volume)
    except ValueError as exc:
        raise ProductionConfigurationError(
            "database path escapes the persistent volume"
        ) from exc
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise ProductionConfigurationError("corpus database is unavailable") from exc
    return digest.hexdigest()


def _check_corpus_permissions(path: Path) -> None:
    try:
        metadata = path.stat()
    except OSError as exc:
        raise ProductionConfigurationError("corpus database is unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise ProductionConfigurationError("corpus database is unavailable")
    if stat.S_IMODE(metadata.st_mode) != 0o444:
        raise ProductionConfigurationError("corpus permissions must be 0444")


def _check_fts5(connection: sqlite3.Connection) -> None:
    try:
        enabled = connection.execute(
            "SELECT sqlite_compileoption_used('ENABLE_FTS5')"
        ).fetchone()
        if enabled is None or int(enabled[0]) != 1:
            raise ProductionConfigurationError("SQLite FTS5 is unavailable")
        connection.execute(
            "SELECT rowid FROM article_passages_fts "
            "WHERE article_passages_fts MATCH ? LIMIT 1",
            ("season",),
        ).fetchone()
    except sqlite3.Error as exc:
        raise ProductionConfigurationError("SQLite FTS5 is unavailable") from exc


def _validate_corpus(path: Path) -> None:
    try:
        connection = sqlite3.connect(
            f"{path.as_uri()}?mode=ro",
            uri=True,
            timeout=5.0,
        )
    except sqlite3.Error as exc:
        raise ProductionConfigurationError("corpus database cannot be opened") from exc

    try:
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchall()
        except sqlite3.Error as exc:
            raise ProductionConfigurationError(
                "corpus SQLite integrity check failed"
            ) from exc
        if integrity != [("ok",)]:
            raise ProductionConfigurationError("corpus SQLite integrity check failed")

        try:
            foreign_key_failure = connection.execute(
                "PRAGMA foreign_key_check"
            ).fetchone()
        except sqlite3.Error as exc:
            raise ProductionConfigurationError(
                "corpus foreign-key validation failed"
            ) from exc
        if foreign_key_failure is not None:
            raise ProductionConfigurationError(
                "corpus foreign-key validation failed"
            )

        _check_fts5(connection)

        try:
            validate_database(connection)
        except (ValidationError, sqlite3.Error) as exc:
            raise ProductionConfigurationError("corpus validation failed") from exc
    finally:
        connection.close()


def _probe_audit_write(path: Path) -> None:
    connection: sqlite3.Connection | None = None
    request_id = f"production-preflight-{os.getpid()}"
    try:
        connection = sqlite3.connect(
            f"{path.as_uri()}?mode=rw",
            uri=True,
            timeout=5.0,
        )
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO ask_requests(
                request_id, submitted_at_utc, question, answer_status,
                routed_intent, answer_text, failure_reason, elapsed_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request_id,
                "1970-01-01T00:00:00+00:00",
                "production preflight write probe",
                "unsupported",
                None,
                "production preflight write probe",
                "production_preflight",
                0,
            ),
        )
        count = connection.execute(
            "SELECT COUNT(*) FROM ask_requests WHERE request_id = ?",
            (request_id,),
        ).fetchone()
        if count is None or int(count[0]) != 1:
            raise sqlite3.DatabaseError("audit write probe was not visible")
        connection.rollback()
    except sqlite3.Error as exc:
        raise ProductionConfigurationError("audit storage is unavailable") from exc
    finally:
        if connection is not None:
            try:
                if connection.in_transaction:
                    connection.rollback()
            except sqlite3.Error:
                pass
            finally:
                connection.close()


def _initialize_audit(path: Path, volume: Path) -> None:
    try:
        initialize_audit_database(path)
        resolved_path = path.resolve(strict=True)
        resolved_path.relative_to(volume)
        resolved_path.chmod(0o600)
        if stat.S_IMODE(resolved_path.stat().st_mode) != 0o600:
            raise OSError("audit database permissions could not be restricted")
        _probe_audit_write(resolved_path)
    except (AuditError, OSError, ValueError) as exc:
        raise ProductionConfigurationError("audit storage is unavailable") from exc


def preflight(environ: Mapping[str, str] | None = None) -> ProductionPaths:
    """Validate production state and initialize only the writable audit database."""
    production_environment = os.environ if environ is None else environ
    expected_volume = EXPECTED_VOLUME_MOUNT.resolve(strict=False)
    configured_volume = Path(
        _required_environment(
            production_environment,
            "RAILWAY_VOLUME_MOUNT_PATH",
        )
    ).resolve(strict=False)
    if configured_volume != expected_volume or not expected_volume.is_dir():
        raise ProductionConfigurationError("persistent volume is unavailable")

    corpus = _resolve_inside_volume(
        _required_environment(production_environment, "DEFIANCE_CORPUS_DATABASE"),
        expected_volume,
    )
    audit = _resolve_inside_volume(
        _required_environment(production_environment, "DEFIANCE_AUDIT_DATABASE"),
        expected_volume,
    )
    if corpus == audit:
        raise ProductionConfigurationError("corpus and audit databases must be distinct")

    configured_sha256 = _required_environment(
        production_environment,
        "DEFIANCE_CORPUS_SHA256",
    ).lower()
    if configured_sha256 != EXPECTED_CORPUS_SHA256:
        raise ProductionConfigurationError("expected corpus SHA-256 is incorrect")

    _check_corpus_permissions(corpus)
    if _sha256(corpus) != EXPECTED_CORPUS_SHA256:
        raise ProductionConfigurationError("corpus SHA-256 mismatch")
    _validate_corpus(corpus)
    if _sha256(corpus) != EXPECTED_CORPUS_SHA256:
        raise ProductionConfigurationError("corpus changed during validation")

    _initialize_audit(audit, expected_volume)
    return ProductionPaths(volume=expected_volume, corpus=corpus, audit=audit)


def main() -> int:
    """Run the production preflight without exposing private paths or tracebacks."""
    os.umask(0o077)
    try:
        preflight()
    except ProductionConfigurationError as exc:
        print(f"Production preflight failed: {exc}", file=sys.stderr)
        return 1
    except Exception:
        print("Production preflight failed: unexpected validation error", file=sys.stderr)
        return 1
    print(
        "Production preflight passed: validated immutable 2017 corpus "
        f"{EXPECTED_CORPUS_SHA256} and writable private audit storage.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
