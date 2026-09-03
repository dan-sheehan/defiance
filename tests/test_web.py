from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlparse
from uuid import UUID

from defiance.answer import AnswerResult, EvidenceReference
from defiance.audit import AuditError
from defiance.corpus_db import SCHEMA
from defiance.web import MAX_QUESTION_CHARACTERS, create_app


ROOT = Path(__file__).resolve().parents[1]
FULL_CORPUS_DATABASE = ROOT / "data" / "normalized" / "2017.sqlite3"


def _result(
    *,
    status: str = "answered",
    text: str = "San Diego State went 42-21 in 2017.",
    intent: str | None = "team_record",
    failure_reason: str | None = None,
    suggestions: tuple[str, ...] = ("Who led San Diego State in home runs in 2017?",),
) -> AnswerResult:
    evidence = (
        EvidenceReference(
            label="2017 SDSU season statistics",
            source_id="sdsu-2017-season-statistics",
            original_url="https://goaztecs.com/news/2018/07/13/2017-baseball-html-statistics",
            source_locator="statistics/table[9]/row[1]",
            raw_path="data/raw/private-source.html",
        ),
    )
    if status != "answered" and failure_reason is None:
        failure_reason = f"test_{status}"
    return AnswerResult(
        question="What was our record in 2017?",
        status=status,
        intent=intent,
        text=text,
        evidence=evidence if status == "answered" else (),
        suggestions=suggestions,
        failure_reason=failure_reason,
    )


class WebApplicationTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.corpus = self.root / "2017.sqlite3"
        self.audit = self.root / "runtime" / "audit.sqlite3"
        with sqlite3.connect(self.corpus) as connection:
            connection.executescript(SCHEMA)
        self.app = create_app(corpus_path=self.corpus, audit_path=self.audit)
        self.app.testing = True
        self.client = self.app.test_client()

    def _audit_count(self) -> int:
        with sqlite3.connect(self.audit) as connection:
            row = connection.execute("SELECT COUNT(*) FROM ask_requests").fetchone()
        return int(row[0])

    def test_homepage_and_packaged_assets(self) -> None:
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/html")
        page = response.get_data(as_text=True)
        for fragment in (
            "2017 · SDSU BASEBALL",
            "SDSU sources only",
            "Start with your full name, or ask a question",
            "Each question stands alone",
            f'maxlength="{MAX_QUESTION_CHARACTERS}"',
            "What happened in the Mountain West Tournament?",
            'aria-live="polite"',
            "Looking through the 2017 SDSU archive…",
        ):
            self.assertIn(fragment, page)
        self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])
        with self.client.get("/static/app.css") as stylesheet:
            self.assertEqual(stylesheet.status_code, 200)
            stylesheet.get_data()
        with self.client.get("/static/app.js") as script:
            self.assertEqual(script.status_code, 200)
            script_text = script.get_data(as_text=True)
        self.assertIn("textContent", script_text)
        self.assertIn("loading.hidden = !value", script_text)
        self.assertIn("setPending(true)", script_text)
        self.assertNotIn("innerHTML", script_text)

    def test_successful_ask_calls_boundary_once_and_writes_exact_audit(self) -> None:
        question = "  What was our record in 2017?  "
        expected = _result()
        with patch("defiance.web.answer_question", return_value=expected) as boundary:
            response = self.client.post("/api/ask", json={"question": question})

        self.assertEqual(response.status_code, 200)
        boundary.assert_called_once_with(self.corpus.resolve(), question)
        payload = response.get_json()
        UUID(payload["request_id"])
        self.assertEqual(
            set(payload),
            {"request_id", "status", "text", "evidence", "suggestions"},
        )
        self.assertEqual(payload["status"], "answered")
        self.assertEqual(payload["text"], expected.text)
        self.assertEqual(
            payload["evidence"],
            [
                {
                    "label": "2017 SDSU season statistics",
                    "original_url": expected.evidence[0].original_url,
                }
            ],
        )
        serialized = response.get_data(as_text=True)
        for private_value in (
            "raw_path",
            "source_locator",
            "source_id",
            "failure_reason",
            "private-source.html",
            "statistics/table[9]/row[1]",
        ):
            self.assertNotIn(private_value, serialized)
        self.assertFalse(response.headers.getlist("Set-Cookie"))

        with sqlite3.connect(self.audit) as connection:
            request_row = connection.execute(
                """
                SELECT request_id, submitted_at_utc, question, answer_status,
                       routed_intent, answer_text, failure_reason, elapsed_ms
                FROM ask_requests
                """
            ).fetchone()
            evidence_row = connection.execute(
                """
                SELECT request_id, evidence_order, label, source_id,
                       source_locator, original_url
                FROM ask_evidence
                """
            ).fetchone()
        self.assertEqual(request_row[0], payload["request_id"])
        self.assertTrue(request_row[1].endswith("Z"))
        self.assertEqual(
            request_row[2:7],
            (question, "answered", "team_record", expected.text, None),
        )
        self.assertGreaterEqual(request_row[7], 0)
        self.assertEqual(evidence_row[0], payload["request_id"])
        self.assertEqual(
            evidence_row[1:],
            (
                0,
                expected.evidence[0].label,
                expected.evidence[0].source_id,
                expected.evidence[0].source_locator,
                expected.evidence[0].original_url,
            ),
        )

    def test_every_answer_status_is_returned_without_reinterpretation(self) -> None:
        statuses = (
            "answered",
            "unknown_entity",
            "ambiguous_entity",
            "unsupported",
            "unavailable",
            "no_evidence",
            "off_topic",
        )
        for status in statuses:
            with self.subTest(status=status):
                expected = _result(
                    status=status,
                    text=f"Exact {status} text.",
                    intent=None if status != "answered" else "team_record",
                    suggestions=(),
                )
                with patch("defiance.web.answer_question", return_value=expected):
                    response = self.client.post(
                        "/api/ask", json={"question": f"Question for {status}"}
                    )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json()["status"], status)
                self.assertEqual(response.get_json()["text"], expected.text)
                with sqlite3.connect(self.audit) as connection:
                    audited = connection.execute(
                        """
                        SELECT answer_status, routed_intent, answer_text, failure_reason
                        FROM ask_requests
                        WHERE question = ?
                        """,
                        (f"Question for {status}",),
                    ).fetchone()
                self.assertEqual(
                    audited,
                    (status, expected.intent, expected.text, expected.failure_reason),
                )

    def test_malformed_and_oversized_requests_never_call_engine_or_audit(self) -> None:
        requests = (
            ({"data": "not json"}, 415),
            ({"data": "{", "content_type": "application/json"}, 400),
            ({"json": {}}, 400),
            ({"json": {"question": "ok", "extra": True}}, 400),
            ({"json": {"question": 42}}, 400),
            ({"json": {"question": "   "}}, 400),
            ({"json": {"question": "x" * (MAX_QUESTION_CHARACTERS + 1)}}, 413),
        )
        with patch("defiance.web.answer_question") as boundary:
            for arguments, status in requests:
                with self.subTest(arguments=arguments):
                    response = self.client.post("/api/ask", **arguments)
                    self.assertEqual(response.status_code, status)
            response = self.client.post(
                "/api/ask",
                data=json.dumps({"question": "x" * 9000}),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 413)

        boundary.assert_not_called()
        self.assertEqual(self._audit_count(), 0)

    def test_audit_failure_fails_closed(self) -> None:
        with (
            patch("defiance.web.answer_question", return_value=_result()) as boundary,
            patch("defiance.web.record_answer", side_effect=AuditError("unavailable")),
        ):
            response = self.client.post(
                "/api/ask", json={"question": "What was our record?"}
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"]["code"], "service_unavailable")
        boundary.assert_called_once()
        self.assertNotIn(str(self.audit), response.get_data(as_text=True))

    def test_unapproved_source_url_is_not_disclosed_or_audited(self) -> None:
        unsafe = AnswerResult(
            question="question",
            status="answered",
            intent="team_record",
            text="answer",
            evidence=(
                EvidenceReference(
                    label="Unsafe",
                    source_id="unsafe",
                    original_url="javascript:alert(1)",
                    source_locator="secret/locator",
                    raw_path="private/path",
                ),
            ),
        )
        with patch("defiance.web.answer_question", return_value=unsafe):
            response = self.client.post("/api/ask", json={"question": "question"})

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("javascript", response.get_data(as_text=True))
        self.assertNotIn("secret", response.get_data(as_text=True))
        self.assertEqual(self._audit_count(), 0)

    def test_repeated_requests_are_independent_and_cookie_free(self) -> None:
        first = _result(text="First exact answer.", suggestions=())
        second = _result(text="Second exact answer.", suggestions=())
        with patch("defiance.web.answer_question", side_effect=(first, second)) as boundary:
            response_one = self.client.post(
                "/api/ask", json={"question": "First question"}
            )
            response_two = self.client.post(
                "/api/ask", json={"question": "Second question"}
            )

        self.assertEqual(boundary.call_count, 2)
        self.assertEqual(response_one.get_json()["text"], "First exact answer.")
        self.assertEqual(response_two.get_json()["text"], "Second exact answer.")
        self.assertNotIn("First", response_two.get_data(as_text=True))
        self.assertFalse(response_one.headers.getlist("Set-Cookie"))
        self.assertFalse(response_two.headers.getlist("Set-Cookie"))
        self.assertEqual(self._audit_count(), 2)

    def test_health_check_and_corpus_remains_unmodified(self) -> None:
        before = sha256(self.corpus.read_bytes()).hexdigest()
        response = self.client.get("/healthz")
        after = sha256(self.corpus.read_bytes()).hexdigest()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok"})
        self.assertEqual(before, after)
        self.assertFalse(Path(f"{self.corpus}-journal").exists())
        self.assertFalse(Path(f"{self.corpus}-wal").exists())
        self.assertFalse(Path(f"{self.corpus}-shm").exists())

        with patch("defiance.web.check_audit_database", side_effect=AuditError("down")):
            unavailable = self.client.get("/healthz")
        self.assertEqual(unavailable.status_code, 503)
        self.assertEqual(unavailable.get_json(), {"status": "unavailable"})


@unittest.skipUnless(
    FULL_CORPUS_DATABASE.is_file(), "full corpus database unavailable"
)
class FullCorpusWebIntegrationTest(unittest.TestCase):
    def test_real_question_paths_are_read_only_stateless_and_privacy_safe(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        audit = Path(temporary.name) / "audit.sqlite3"
        sidecars = tuple(
            Path(f"{FULL_CORPUS_DATABASE}{suffix}")
            for suffix in ("-journal", "-wal", "-shm")
        )
        self.assertFalse(any(path.exists() for path in sidecars))
        before = sha256(FULL_CORPUS_DATABASE.read_bytes()).hexdigest()
        app = create_app(corpus_path=FULL_CORPUS_DATABASE, audit_path=audit)
        app.testing = True
        client = app.test_client()
        questions = (
            "What was San Diego State's record in 2017?",
            "How many home runs did John Smith hit in 2017?",
            "Danny Sheehan",
            "Danny Sheehan",
            "What happened in the Mountain West Tournament?",
            "How many home runs did Danny Sheehan'; DROP TABLE players; -- hit in 2017?",
        )
        returned: list[tuple[str, str, str]] = []
        for question in questions:
            with self.subTest(question=question):
                response = client.post("/api/ask", json={"question": question})
                self.assertEqual(response.status_code, 200)
                payload = response.get_json()
                returned.append((question, payload["status"], payload["text"]))
                self.assertEqual(
                    set(payload),
                    {"request_id", "status", "text", "evidence", "suggestions"},
                )
                for reference in payload["evidence"]:
                    self.assertIn(
                        urlparse(reference["original_url"]).hostname,
                        {"goaztecs.com", "sandiegost_ftp.sidearmsports.com"},
                    )
                serialized = response.get_data(as_text=True)
                for private_value in (
                    "raw_path",
                    "source_locator",
                    "source_id",
                    "failure_reason",
                    "data/raw",
                    str(ROOT),
                    ".sqlite3",
                ):
                    self.assertNotIn(private_value, serialized)

        with sqlite3.connect(audit) as connection:
            audited = connection.execute(
                """
                SELECT question, answer_status, answer_text
                FROM ask_requests
                ORDER BY rowid
                """
            ).fetchall()
        self.assertEqual(audited, returned)
        self.assertEqual(returned[2], returned[3])
        self.assertEqual(before, sha256(FULL_CORPUS_DATABASE.read_bytes()).hexdigest())
        self.assertFalse(any(path.exists() for path in sidecars))


if __name__ == "__main__":
    unittest.main()
