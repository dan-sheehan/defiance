from __future__ import annotations

from contextlib import redirect_stderr
import hashlib
import io
import json
from pathlib import Path
import shutil
import sqlite3
import stat
import tempfile
import unittest
from unittest import mock

from defiance import production
from defiance.audit import AuditError
from defiance.db import ValidationError


RELEASE_CORPUS_SHA256 = (
    "295f6fb5325f8b82be2d8a12d2ae7106f70560824aca4394c483850d9b6c3245"
)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _create_test_corpus(path: Path, *, invalid_foreign_key: bool = False) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            PRAGMA foreign_keys = OFF;
            CREATE TABLE parent (id INTEGER PRIMARY KEY);
            CREATE TABLE child (
                id INTEGER PRIMARY KEY,
                parent_id INTEGER NOT NULL REFERENCES parent(id)
            );
            CREATE VIRTUAL TABLE article_passages_fts USING fts5(body);
            INSERT INTO article_passages_fts(body) VALUES ('season result');
            """
        )
        if invalid_foreign_key:
            connection.execute("INSERT INTO child(id, parent_id) VALUES (1, 999)")
        connection.commit()
    finally:
        connection.close()


class ProductionConstantTests(unittest.TestCase):
    def test_release_hash_is_pinned(self) -> None:
        self.assertEqual(production.EXPECTED_CORPUS_SHA256, RELEASE_CORPUS_SHA256)
        self.assertEqual(production.EXPECTED_VOLUME_MOUNT, Path("/data"))


class RailwayConfigurationTests(unittest.TestCase):
    def test_railway_uses_strict_preflight_and_one_sync_gunicorn_worker(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        configuration = json.loads((repository / "railway.json").read_text())
        deploy = configuration["deploy"]
        start = deploy["startCommand"]

        self.assertEqual(configuration["build"], {"builder": "RAILPACK"})
        self.assertIn(f"chmod 0444 /data/2017-{RELEASE_CORPUS_SHA256}.sqlite3", start)
        self.assertIn("python -m defiance.production", start)
        self.assertIn("--workers 1", start)
        self.assertIn("--worker-class sync", start)
        self.assertIn("--access-logfile /dev/null", start)
        self.assertIn("--no-control-socket", start)
        self.assertIn("'defiance.web:create_app()'", start)
        self.assertEqual(deploy["healthcheckPath"], "/healthz")
        self.assertEqual(deploy["healthcheckTimeout"], 60)
        self.assertEqual(deploy["restartPolicyType"], "ON_FAILURE")
        self.assertEqual(deploy["restartPolicyMaxRetries"], 10)
        self.assertEqual(deploy["drainingSeconds"], "30")


class ProductionPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.volume = self.root / "data"
        self.volume.mkdir()
        self.corpus = self.volume / "2017-test.sqlite3"
        self.audit = self.volume / "audit.sqlite3"
        _create_test_corpus(self.corpus)
        self.corpus.chmod(0o444)
        self.sha256 = _file_sha256(self.corpus)
        self.environment = {
            "RAILWAY_VOLUME_MOUNT_PATH": str(self.volume),
            "DEFIANCE_CORPUS_DATABASE": str(self.corpus),
            "DEFIANCE_CORPUS_SHA256": self.sha256,
            "DEFIANCE_AUDIT_DATABASE": str(self.audit),
        }

        self.mount_patch = mock.patch.object(
            production,
            "EXPECTED_VOLUME_MOUNT",
            self.volume,
        )
        self.hash_patch = mock.patch.object(
            production,
            "EXPECTED_CORPUS_SHA256",
            self.sha256,
        )
        self.validation_patch = mock.patch.object(production, "validate_database")
        self.mount_patch.start()
        self.hash_patch.start()
        self.validation = self.validation_patch.start()
        self.addCleanup(self.validation_patch.stop)
        self.addCleanup(self.hash_patch.stop)
        self.addCleanup(self.mount_patch.stop)

    def test_valid_preflight_preserves_corpus_and_initializes_private_audit(self) -> None:
        before = _file_sha256(self.corpus)

        paths = production.preflight(self.environment)

        self.assertEqual(paths.volume, self.volume.resolve())
        self.assertEqual(paths.corpus, self.corpus.resolve())
        self.assertEqual(paths.audit, self.audit.resolve())
        self.assertEqual(_file_sha256(self.corpus), before)
        self.assertEqual(stat.S_IMODE(self.corpus.stat().st_mode), 0o444)
        self.assertEqual(stat.S_IMODE(self.audit.stat().st_mode), 0o600)
        self.assertEqual(list(self.volume.glob(f"{self.corpus.name}-*")), [])
        connection = sqlite3.connect(self.audit)
        try:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM ask_requests").fetchone()[0],
                0,
            )
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_schema WHERE type = 'table'"
                )
            }
        finally:
            connection.close()
        self.assertTrue({"ask_requests", "ask_evidence"}.issubset(tables))
        self.validation.assert_called_once()

    def test_missing_volume_fails_closed(self) -> None:
        missing = self.root / "missing"
        environment = dict(self.environment)
        environment["RAILWAY_VOLUME_MOUNT_PATH"] = str(missing)
        with mock.patch.object(production, "EXPECTED_VOLUME_MOUNT", missing):
            with self.assertRaisesRegex(
                production.ProductionConfigurationError,
                "persistent volume is unavailable",
            ):
                production.preflight(environment)

    def test_missing_required_environment_fails_closed(self) -> None:
        for name in (
            "RAILWAY_VOLUME_MOUNT_PATH",
            "DEFIANCE_CORPUS_DATABASE",
            "DEFIANCE_CORPUS_SHA256",
            "DEFIANCE_AUDIT_DATABASE",
        ):
            with self.subTest(name=name):
                environment = dict(self.environment)
                del environment[name]
                with self.assertRaisesRegex(
                    production.ProductionConfigurationError,
                    "required production configuration is missing",
                ):
                    production.preflight(environment)

    def test_corpus_path_outside_volume_fails_closed(self) -> None:
        environment = dict(self.environment)
        environment["DEFIANCE_CORPUS_DATABASE"] = str(self.root / "corpus.sqlite3")
        with self.assertRaisesRegex(
            production.ProductionConfigurationError,
            "database path escapes the persistent volume",
        ):
            production.preflight(environment)

    def test_relative_database_paths_never_fall_back_to_checkout(self) -> None:
        for name in (
            "DEFIANCE_CORPUS_DATABASE",
            "DEFIANCE_AUDIT_DATABASE",
        ):
            with self.subTest(name=name):
                environment = dict(self.environment)
                environment[name] = "data/runtime.sqlite3"
                with self.assertRaisesRegex(
                    production.ProductionConfigurationError,
                    "database path must be absolute",
                ):
                    production.preflight(environment)

    def test_audit_path_outside_volume_fails_closed(self) -> None:
        environment = dict(self.environment)
        environment["DEFIANCE_AUDIT_DATABASE"] = str(self.root / "audit.sqlite3")
        with self.assertRaisesRegex(
            production.ProductionConfigurationError,
            "database path escapes the persistent volume",
        ):
            production.preflight(environment)

    def test_corpus_and_audit_must_be_distinct(self) -> None:
        environment = dict(self.environment)
        environment["DEFIANCE_AUDIT_DATABASE"] = str(self.corpus)
        with self.assertRaisesRegex(
            production.ProductionConfigurationError,
            "must be distinct",
        ):
            production.preflight(environment)

    def test_configured_hash_must_match_pinned_hash(self) -> None:
        environment = dict(self.environment)
        environment["DEFIANCE_CORPUS_SHA256"] = "0" * 64
        with self.assertRaisesRegex(
            production.ProductionConfigurationError,
            "expected corpus SHA-256 is incorrect",
        ):
            production.preflight(environment)

    def test_corpus_hash_mismatch_fails_closed(self) -> None:
        self.corpus.chmod(0o644)
        with self.corpus.open("ab") as target:
            target.write(b"changed")
        self.corpus.chmod(0o444)
        with self.assertRaisesRegex(
            production.ProductionConfigurationError,
            "corpus SHA-256 mismatch",
        ):
            production.preflight(self.environment)

    def test_corpus_permissions_must_be_exactly_read_only(self) -> None:
        self.corpus.chmod(0o644)
        with self.assertRaisesRegex(
            production.ProductionConfigurationError,
            "corpus permissions must be 0444",
        ):
            production.preflight(self.environment)

    def test_corrupt_sqlite_fails_integrity_check(self) -> None:
        self.corpus.chmod(0o644)
        self.corpus.write_bytes(b"not a sqlite database")
        self.corpus.chmod(0o444)
        corrupt_sha256 = _file_sha256(self.corpus)
        environment = dict(self.environment)
        environment["DEFIANCE_CORPUS_SHA256"] = corrupt_sha256
        with mock.patch.object(
            production,
            "EXPECTED_CORPUS_SHA256",
            corrupt_sha256,
        ):
            with self.assertRaisesRegex(
                production.ProductionConfigurationError,
                "corpus SQLite integrity check failed",
            ):
                production.preflight(environment)

    def test_foreign_key_violation_fails_closed(self) -> None:
        self.corpus.chmod(0o644)
        self.corpus.unlink()
        _create_test_corpus(self.corpus, invalid_foreign_key=True)
        self.corpus.chmod(0o444)
        invalid_sha256 = _file_sha256(self.corpus)
        environment = dict(self.environment)
        environment["DEFIANCE_CORPUS_SHA256"] = invalid_sha256
        with mock.patch.object(
            production,
            "EXPECTED_CORPUS_SHA256",
            invalid_sha256,
        ):
            with self.assertRaisesRegex(
                production.ProductionConfigurationError,
                "corpus foreign-key validation failed",
            ):
                production.preflight(environment)

    def test_fts5_unavailable_fails_closed(self) -> None:
        with mock.patch.object(
            production,
            "_check_fts5",
            side_effect=production.ProductionConfigurationError(
                "SQLite FTS5 is unavailable"
            ),
        ):
            with self.assertRaisesRegex(
                production.ProductionConfigurationError,
                "SQLite FTS5 is unavailable",
            ):
                production.preflight(self.environment)

    def test_corpus_validation_failure_fails_closed(self) -> None:
        self.validation.side_effect = ValidationError("invalid test corpus")
        with self.assertRaisesRegex(
            production.ProductionConfigurationError,
            "corpus validation failed",
        ):
            production.preflight(self.environment)

    def test_audit_initialization_failure_fails_closed(self) -> None:
        with mock.patch.object(
            production,
            "initialize_audit_database",
            side_effect=AuditError("test failure"),
        ):
            with self.assertRaisesRegex(
                production.ProductionConfigurationError,
                "audit storage is unavailable",
            ):
                production.preflight(self.environment)

    def test_audit_write_check_failure_fails_closed(self) -> None:
        with mock.patch.object(
            production,
            "_probe_audit_write",
            side_effect=production.ProductionConfigurationError(
                "audit storage is unavailable"
            ),
        ):
            with self.assertRaisesRegex(
                production.ProductionConfigurationError,
                "audit storage is unavailable",
            ):
                production.preflight(self.environment)

    def test_main_returns_failure_without_disclosing_database_path(self) -> None:
        environment = dict(self.environment)
        environment["DEFIANCE_CORPUS_DATABASE"] = str(
            self.volume / "private-corpus-name.sqlite3"
        )
        stderr = io.StringIO()
        with (
            mock.patch.dict(production.os.environ, environment, clear=True),
            mock.patch.object(production.os, "umask"),
            redirect_stderr(stderr),
        ):
            result = production.main()

        self.assertEqual(result, 1)
        self.assertIn("Production preflight failed", stderr.getvalue())
        self.assertNotIn("private-corpus-name", stderr.getvalue())

    def test_main_hides_unexpected_preflight_failure(self) -> None:
        stderr = io.StringIO()
        with (
            mock.patch.object(
                production,
                "preflight",
                side_effect=RuntimeError("/private/path/unexpected"),
            ),
            mock.patch.object(production.os, "umask"),
            redirect_stderr(stderr),
        ):
            result = production.main()

        self.assertEqual(result, 1)
        self.assertEqual(
            stderr.getvalue(),
            "Production preflight failed: unexpected validation error\n",
        )


class ReleaseCorpusPreflightTests(unittest.TestCase):
    def test_validated_release_corpus_passes_full_preflight_unchanged(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        source_corpus = repository / "data" / "normalized" / "2017.sqlite3"
        if not source_corpus.is_file():
            self.skipTest("validated local 2017 corpus is not present")

        with tempfile.TemporaryDirectory() as temporary_directory:
            volume = Path(temporary_directory) / "data"
            volume.mkdir()
            corpus = volume / f"2017-{RELEASE_CORPUS_SHA256}.sqlite3"
            audit = volume / "audit.sqlite3"
            shutil.copyfile(source_corpus, corpus)
            corpus.chmod(0o444)
            environment = {
                "RAILWAY_VOLUME_MOUNT_PATH": str(volume),
                "DEFIANCE_CORPUS_DATABASE": str(corpus),
                "DEFIANCE_CORPUS_SHA256": RELEASE_CORPUS_SHA256,
                "DEFIANCE_AUDIT_DATABASE": str(audit),
            }
            before = _file_sha256(corpus)

            with mock.patch.object(production, "EXPECTED_VOLUME_MOUNT", volume):
                production.preflight(environment)

            self.assertEqual(before, RELEASE_CORPUS_SHA256)
            self.assertEqual(_file_sha256(corpus), RELEASE_CORPUS_SHA256)
            self.assertEqual(stat.S_IMODE(corpus.stat().st_mode), 0o444)
            self.assertEqual(stat.S_IMODE(audit.stat().st_mode), 0o600)
            self.assertEqual(list(volume.glob(f"{corpus.name}-*")), [])


if __name__ == "__main__":
    unittest.main()
