"""Thin mobile web interface over the deterministic Defiance answer engine."""

from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path
import sqlite3
from time import perf_counter_ns
from urllib.parse import urlparse
from uuid import uuid4

from flask import Flask, Response, jsonify, render_template, request

from .answer import AnswerResult, answer_question
from .audit import (
    AuditError,
    check_audit_database,
    initialize_audit_database,
    record_answer,
)
from .query import QueryError


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS_DATABASE = REPOSITORY_ROOT / "data" / "normalized" / "2017.sqlite3"
DEFAULT_AUDIT_DATABASE = REPOSITORY_ROOT / "data" / "runtime" / "audit.sqlite3"
MAX_QUESTION_CHARACTERS = 500
MAX_REQUEST_BYTES = 8 * 1024
PUBLIC_SOURCE_HOSTS = frozenset(
    {"goaztecs.com", "sandiegost_ftp.sidearmsports.com"}
)


class WebConfigurationError(RuntimeError):
    """Raised when the web application cannot start or disclose data safely."""


def _configured_path(explicit: Path | None, environment_name: str, default: Path) -> Path:
    value = explicit or Path(os.environ.get(environment_name, default))
    return value.expanduser().resolve()


def _check_corpus_database(database_path: Path) -> None:
    if not database_path.is_file():
        raise WebConfigurationError("the validated corpus database is unavailable")
    try:
        connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
        try:
            result = connection.execute("PRAGMA quick_check").fetchone()
            if result is None or result[0] != "ok":
                raise WebConfigurationError("the validated corpus database is unhealthy")
            connection.execute("SELECT 1 FROM players LIMIT 1").fetchone()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise WebConfigurationError("the validated corpus database is unavailable") from exc


def _public_result(request_id: str, result: AnswerResult) -> dict[str, object]:
    evidence: list[dict[str, str]] = []
    for reference in result.evidence:
        parsed = urlparse(reference.original_url)
        if parsed.scheme != "https" or parsed.hostname not in PUBLIC_SOURCE_HOSTS:
            raise WebConfigurationError("an evidence URL is not approved for disclosure")
        evidence.append(
            {
                "label": reference.label,
                "original_url": reference.original_url,
            }
        )
    return {
        "request_id": request_id,
        "status": result.status,
        "text": result.text,
        "evidence": evidence,
        "suggestions": list(result.suggestions),
    }


def _error(code: str, message: str, status: int, request_id: str | None = None) -> Response:
    payload: dict[str, object] = {"error": {"code": code, "message": message}}
    if request_id is not None:
        payload["request_id"] = request_id
    response = jsonify(payload)
    response.status_code = status
    return response


def create_app(
    *,
    corpus_path: Path | None = None,
    audit_path: Path | None = None,
) -> Flask:
    """Create the WSGI application around explicit corpus and audit paths."""
    corpus_database = _configured_path(
        corpus_path,
        "DEFIANCE_CORPUS_DATABASE",
        DEFAULT_CORPUS_DATABASE,
    )
    audit_database = _configured_path(
        audit_path,
        "DEFIANCE_AUDIT_DATABASE",
        DEFAULT_AUDIT_DATABASE,
    )
    if corpus_database == audit_database:
        raise WebConfigurationError("corpus and audit databases must be separate")
    _check_corpus_database(corpus_database)
    initialize_audit_database(audit_database)

    app = Flask(__name__)
    app.config.update(
        CORPUS_DATABASE=corpus_database,
        AUDIT_DATABASE=audit_database,
        MAX_CONTENT_LENGTH=MAX_REQUEST_BYTES,
    )

    @app.after_request
    def secure_response(response: Response) -> Response:
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; base-uri 'none'; connect-src 'self'; "
            "form-action 'self'; frame-ancestors 'none'; img-src 'self' data:; "
            "script-src 'self'; style-src 'self'"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        if request.path.startswith("/api/") or request.path == "/healthz":
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    def homepage() -> str:
        return render_template(
            "index.html",
            max_question_characters=MAX_QUESTION_CHARACTERS,
        )

    @app.post("/api/ask")
    def ask() -> Response:
        if not request.is_json:
            return _error(
                "unsupported_media_type",
                "Send the question as JSON.",
                415,
            )
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) != {"question"}:
            return _error(
                "invalid_request",
                'Send one JSON field named "question".',
                400,
            )
        question = body["question"]
        if not isinstance(question, str) or not question.strip():
            return _error(
                "invalid_request",
                "Question must be a non-empty string.",
                400,
            )
        if len(question) > MAX_QUESTION_CHARACTERS:
            return _error(
                "question_too_long",
                f"Question must be {MAX_QUESTION_CHARACTERS} characters or fewer.",
                413,
            )

        request_id = str(uuid4())
        submitted_at = datetime.now(UTC).isoformat(timespec="milliseconds").replace(
            "+00:00", "Z"
        )
        started = perf_counter_ns()
        try:
            result = answer_question(app.config["CORPUS_DATABASE"], question)
            payload = _public_result(request_id, result)
            elapsed_ms = max(0, (perf_counter_ns() - started) // 1_000_000)
            record_answer(
                app.config["AUDIT_DATABASE"],
                request_id=request_id,
                submitted_at_utc=submitted_at,
                question=question,
                result=result,
                elapsed_ms=elapsed_ms,
            )
        except AuditError:
            return _error(
                "service_unavailable",
                "Defiance is temporarily unavailable. Try again.",
                503,
                request_id,
            )
        except (QueryError, WebConfigurationError, OSError, sqlite3.Error):
            return _error(
                "service_unavailable",
                "Defiance is temporarily unavailable. Try again.",
                503,
                request_id,
            )
        except Exception:
            app.logger.exception("accepted ask request failed")
            return _error(
                "internal_error",
                "Defiance couldn't answer that right now. Try again.",
                500,
                request_id,
            )
        return jsonify(payload)

    @app.get("/healthz")
    def health() -> Response:
        try:
            _check_corpus_database(app.config["CORPUS_DATABASE"])
            check_audit_database(app.config["AUDIT_DATABASE"])
        except (AuditError, WebConfigurationError):
            return jsonify({"status": "unavailable"}), 503
        return jsonify({"status": "ok"})

    @app.errorhandler(413)
    def request_too_large(_error_value: Exception) -> Response:
        return _error(
            "request_too_large",
            f"Request body must be {MAX_REQUEST_BYTES} bytes or fewer.",
            413,
        )

    return app
