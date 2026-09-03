from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from defiance import answer, cli
from defiance.answer import AnswerResult, answer_question
from defiance.corpus import build_corpus
from defiance.corpus_db import SCHEMA


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "config" / "2017" / "corpus.json"


def _raw_corpus_is_present() -> bool:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return all(
        (ROOT / source["raw_path"]).is_file()
        for source in manifest["sources"]
        if source["in_scope"] and source["status"] == "available"
    )


class DeterministicRouterUnitTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.database = root / "questions.sqlite3"
        self.aliases = root / "aliases.json"
        self.aliases.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "team": ["San Diego State", "SDSU", "Aztecs", "we", "our"],
                    "players": {},
                    "staff": {},
                    "opponents": {"UNLV": ["UNLV", "Rebels"]},
                    "events": {},
                    "record_splits": {"1": ["overall record", "season record"]},
                }
            ),
            encoding="utf-8",
        )
        with sqlite3.connect(self.database) as connection:
            connection.executescript(SCHEMA)
            connection.execute(
                """
                INSERT INTO sources(
                    source_id, kind, original_url, sha256, raw_path, in_scope,
                    status, classification, title, notes
                ) VALUES ('source', 'recap', 'https://example.test/source',
                          'hash', 'raw/source.html', 1, 'available', 'recap',
                          'Source', NULL)
                """
            )
            connection.execute(
                """
                INSERT INTO games(
                    game_id, schedule_order, game_date, opponent, source_opponent,
                    designation, schedule_result, location, tournament,
                    schedule_sdsu_score, schedule_opponent_score, sdsu_score,
                    opponent_score, schedule_source_id, schedule_source_locator,
                    score_source_id, score_source_locator
                ) VALUES ('game', 1, '2017-03-17', 'UNLV', 'UNLV', 'vs',
                          'W 2-1', 'San Diego', NULL, 2, 1, 2, 1,
                          'source', 'schedule', 'source', 'score')
                """
            )
            connection.executemany(
                """
                INSERT INTO players(
                    player_id, jersey_number, full_name, position, height,
                    weight, class_year, hometown, high_school, previous_school,
                    source_id, source_locator
                ) VALUES (?, '1', ?, ?, '6-0', '190', 'SR', 'San Diego',
                          'High School', NULL, 'source', 'roster')
                """,
                (
                    ("andrew-brown", "Andrew Brown", "INF"),
                    ("danny-sheehan", "Danny Sheehan", "INF"),
                    ("tre-brown", "Tre Brown", "RHP"),
                ),
            )
            connection.execute(
                """
                INSERT INTO staff(staff_id, full_name, title, source_id, source_locator)
                VALUES ('mark-martinez', 'Mark Martinez', 'Head Coach',
                        'source', 'roster')
                """
            )
            connection.execute(
                """
                INSERT INTO season_records(
                    record_order, label, wins, losses, source_id, source_locator
                ) VALUES (1, 'Overall', 42, 21, 'source', 'record')
                """
            )
        self.alias_patch = patch.object(answer, "ALIASES_PATH", self.aliases)
        self.alias_patch.start()
        self.addCleanup(self.alias_patch.stop)

    def test_unknown_ambiguous_off_topic_and_stateless_fail_safely(self) -> None:
        ambiguous = answer_question(self.database, "What were Brown's 2017 stats?")
        unknown = answer_question(
            self.database, "How many home runs did John Smith hit in 2017?"
        )
        off_topic = answer_question(self.database, "What is the weather in San Diego?")
        context = answer_question(self.database, "What about Saturday?")

        self.assertEqual(ambiguous.status, "ambiguous_entity")
        self.assertIn("Andrew Brown", ambiguous.text)
        self.assertIn("Tre Brown", ambiguous.text)
        self.assertEqual(unknown.status, "unknown_entity")
        self.assertEqual(off_topic.status, "off_topic")
        self.assertEqual(context.failure_reason, "missing_conversational_context")

        question = "What was our record in 2017?"
        self.assertEqual(
            answer_question(self.database, question),
            answer_question(self.database, question),
        )

    def test_injection_shaped_input_does_not_change_the_database(self) -> None:
        malicious = (
            "How many home runs did Danny Sheehan'; DROP TABLE players; -- hit in 2017?"
        )
        result = answer_question(self.database, malicious)
        self.assertIn(result.status, {"answered", "unknown_entity", "unsupported"})
        with sqlite3.connect(f"file:{self.database}?mode=ro", uri=True) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM players").fetchone()[0], 3)


class AnswerCliTest(unittest.TestCase):
    def test_ask_uses_the_product_answer_boundary(self) -> None:
        result = AnswerResult(
            question="What was our record?",
            status="answered",
            intent="team_record",
            text="San Diego State went 42-21 in 2017.",
            evidence=(
                answer.EvidenceReference(
                    label="Season statistics",
                    source_id="source",
                    original_url="https://example.test/source",
                    source_locator="record",
                    raw_path="raw/source.html",
                ),
            ),
        )
        with (
            patch.object(cli, "answer_question", return_value=result) as boundary,
            redirect_stdout(io.StringIO()) as stdout,
        ):
            status = cli.main(["ask", "What was our record?"])

        self.assertEqual(status, 0)
        boundary.assert_called_once_with(
            cli.FULL_DATABASE_PATH, "What was our record?"
        )
        self.assertIn("San Diego State went 42-21", stdout.getvalue())


@unittest.skipUnless(_raw_corpus_is_present(), "preserved full corpus is not present")
class FullCorpusAnswerAcceptanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.database = Path(cls.temporary.name) / "2017.sqlite3"
        build_corpus(ROOT, cls.database)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_committed_representative_acceptance_matrix(self) -> None:
        cases = (
            (
                "everyday hitter / season batting",
                "How many home runs did Danny Sheehan hit in 2017?",
                "answered",
                "season_player_batting",
                ("7 home runs",),
            ),
            (
                "everyday pitcher / season pitching",
                "How many strikeouts did Brett Seeburger have in 2017?",
                "answered",
                "season_player_pitching",
                ("69 strikeouts",),
            ),
            (
                "sparse hitter",
                "What were CJ Saylor's batting stats in 2017?",
                "answered",
                "season_player_batting",
                ("0-for-3", ".000"),
            ),
            (
                "sparse pitcher",
                "What were Tre Brown's pitching stats in 2017?",
                "answered",
                "season_player_pitching",
                ("1.0 innings", "1 strikeout", "2 appearances"),
            ),
            (
                "single-game stat",
                "What did Danny Sheehan do against UNLV on April 15, 2017?",
                "answered",
                "single_game_player",
                ("2-for-5", "3 runs", "2 RBI", "1 home run"),
            ),
            (
                "opponent batting aggregation",
                "What did Danny Sheehan hit against UNLV in 2017?",
                "answered",
                "opponent_player",
                ("9-for-25", ".360", "across 6 games"),
            ),
            (
                "opponent single-metric aggregation",
                "How many hits did Danny Sheehan have against UNLV in 2017?",
                "answered",
                "opponent_player",
                ("9 hits",),
            ),
            (
                "opponent pitching aggregation",
                "How did Brett Seeburger pitch against Nevada in 2017?",
                "answered",
                "opponent_player",
                ("12.1 innings", "2.92 ERA", "7 strikeouts", "2-0 record"),
            ),
            (
                "series aggregation",
                "What did Danny Sheehan hit in the road series at UNLV?",
                "answered",
                "series_player",
                ("5-for-13", ".385", "4 RBI"),
            ),
            (
                "best series",
                "What was Danny Sheehan's best series?",
                "answered",
                "hitter_best_series",
                ("Air Force road series", "9-for-14", ".643"),
            ),
            (
                "team leader",
                "Who led San Diego State in home runs in 2017?",
                "answered",
                "team_leader",
                ("Tyler Adkison", "15"),
            ),
            (
                "team record",
                "What was our record in 2017?",
                "answered",
                "team_record",
                ("42-21",),
            ),
            (
                "record split",
                "What was SDSU's conference record?",
                "answered",
                "team_record",
                ("20-10", "conference"),
            ),
            (
                "game result",
                "What was the result of the UCLA game on June 3, 2017?",
                "answered",
                "game_result",
                ("beat UCLA 3-2",),
            ),
            (
                "series result",
                "How did SDSU do in the road series at UNLV?",
                "answered",
                "series_result",
                ("2-1", "3-7", "20-6", "16-3"),
            ),
            (
                "tournament result",
                "What was SDSU's record in the Mountain West Tournament?",
                "answered",
                "event_result",
                ("3-1", "18-10", "9-8", "1-12", "5-3"),
            ),
            (
                "tournament narrative",
                "What happened in the Mountain West Tournament?",
                "answered",
                "event_recap",
                ("3-1", "Mountain West baseball champion"),
            ),
            (
                "game recap",
                "What happened against UCLA on June 3, 2017?",
                "answered",
                "game_recap",
                ("3-2", "13 innings", "winning run"),
            ),
            (
                "series narrative",
                "What happened in the road series at UNLV?",
                "answered",
                "series_recap",
                ("2-1", "2017-04-13", "2017-04-14", "2017-04-15"),
            ),
            (
                "player narrative",
                "What did the recap say about Danny Sheehan in the June 3 UCLA game?",
                "answered",
                "person_narrative",
                ("hit by pitch", "winning run"),
            ),
            (
                "staff narrative",
                "What did SDSU say about Mark Martinez's 100th win?",
                "answered",
                "person_narrative",
                ("100th win", "head coach"),
            ),
            (
                "ambiguous player",
                "What were Brown's 2017 stats?",
                "ambiguous_entity",
                None,
                ("Andrew Brown", "Tre Brown"),
            ),
            (
                "ambiguous game",
                "What happened in the UNLV game?",
                "ambiguous_entity",
                None,
                ("multiple games", "exact date"),
            ),
            (
                "unknown player",
                "How many home runs did John Smith hit in 2017?",
                "unknown_entity",
                None,
                ("John Smith", "full player"),
            ),
            (
                "unavailable aggregate",
                "How many hits did Danny Sheehan have against Fresno State?",
                "unavailable",
                "opponent_player",
                ("missing a box score", "can't give an exact"),
            ),
            (
                "no narrative evidence",
                "What did the recap say about Tre Brown in the April 15 UNLV game?",
                "no_evidence",
                "person_narrative",
                ("no linked SDSU passage",),
            ),
            (
                "unsupported baseball",
                "What was SDSU's batting average with runners in scoring position?",
                "unsupported",
                None,
                ("outside the supported V1 categories",),
            ),
            (
                "missing context",
                "What about Saturday?",
                "unsupported",
                None,
                ("Each question stands alone",),
            ),
            (
                "off topic",
                "What was the weather in San Diego?",
                "off_topic",
                None,
                ("2017 San Diego State baseball season",),
            ),
        )
        for label, question, status, intent, fragments in cases:
            with self.subTest(label=label):
                result = answer_question(self.database, question)
                self.assertEqual(result.status, status)
                self.assertEqual(result.intent, intent)
                for fragment in fragments:
                    self.assertIn(fragment, result.text)
                if status == "answered":
                    self.assertTrue(result.evidence)
                    for reference in result.evidence:
                        self.assertTrue(reference.source_id)
                        self.assertTrue(reference.original_url.startswith("https://"))
                        self.assertTrue(reference.source_locator)
                        self.assertTrue(reference.raw_path)
                else:
                    self.assertTrue(result.failure_reason)
                for suggestion in result.suggestions:
                    suggested = answer_question(self.database, suggestion)
                    self.assertEqual(
                        suggested.status,
                        "answered",
                        f"suggestion did not re-parse: {suggestion}",
                    )

    def test_aliases_suggestions_injection_and_repeatability(self) -> None:
        alias = answer_question(
            self.database, "What were C.J. Saylor's pitching stats in 2017?"
        )
        self.assertEqual(alias.status, "answered")
        self.assertIn("13 saves", alias.text)

        answered = answer_question(
            self.database, "How many home runs did Danny Sheehan hit in 2017?"
        )
        self.assertTrue(answered.suggestions)
        for suggestion in answered.suggestions:
            reparsed = answer_question(self.database, suggestion)
            self.assertEqual(reparsed.status, "answered")

        question = "What did Danny Sheehan hit against UNLV in 2017?"
        self.assertEqual(
            answer_question(self.database, question),
            answer_question(self.database, question),
        )

        malicious = (
            "How many home runs did Danny Sheehan'; DROP TABLE games; -- hit in 2017?"
        )
        answer_question(self.database, malicious)
        fts = (
            'What did the recap say about Danny Sheehan and "UCLA OR *" '
            "in the June 3 UCLA game?"
        )
        answer_question(self.database, fts)
        with sqlite3.connect(f"file:{self.database}?mode=ro", uri=True) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM games").fetchone()[0], 63)

    def test_ambiguous_and_unavailable_never_return_partial_facts(self) -> None:
        ambiguous = answer_question(self.database, "What happened in the UNLV game?")
        unavailable = answer_question(
            self.database, "How many hits did Danny Sheehan have against Fresno State?"
        )
        self.assertNotIn("beat UNLV", ambiguous.text)
        self.assertNotIn("lost to UNLV", ambiguous.text)
        self.assertNotIn("-for-", unavailable.text)
        self.assertNotIn(" hits against", unavailable.text)


if __name__ == "__main__":
    unittest.main()
