from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from defiance.corpus import build_corpus
from defiance.corpus_db import SCHEMA
from defiance.query import (
    QueryError,
    retrieve_article_passages,
    retrieve_play_by_play_passages,
    show_game,
)


ROOT = Path(__file__).resolve().parents[1]


def _raw_corpus_is_present() -> bool:
    manifest = json.loads(
        (ROOT / "config" / "2017" / "corpus.json").read_text(encoding="utf-8")
    )
    return all(
        (ROOT / source["raw_path"]).is_file()
        for source in manifest["sources"]
        if source["in_scope"] and source["status"] == "available"
    )


class NarrativeQueryTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.database = Path(temporary.name) / "narrative.sqlite3"
        with sqlite3.connect(self.database) as connection:
            connection.executescript(SCHEMA)
            connection.executemany(
                """
                INSERT INTO sources(
                    source_id, kind, original_url, sha256, raw_path, in_scope,
                    status, classification, title, notes
                ) VALUES (?, 'recap', ?, 'hash', ?, 1, 'available', ?, ?, NULL)
                """,
                (
                    ("source-game", "https://example.test/game", "raw/game.html", "recap", "Game"),
                    (
                        "source-series",
                        "https://example.test/series",
                        "raw/series.html",
                        "game_or_series_context",
                        "Series",
                    ),
                    (
                        "source-honor",
                        "https://example.test/honor",
                        "raw/honor.html",
                        "season_honor",
                        "Honor",
                    ),
                ),
            )
            connection.executemany(
                """
                INSERT INTO games(
                    game_id, schedule_order, game_date, opponent, source_opponent,
                    designation, schedule_result, location, tournament,
                    schedule_sdsu_score, schedule_opponent_score, sdsu_score,
                    opponent_score, schedule_source_id, schedule_source_locator,
                    score_source_id, score_source_locator
                ) VALUES (?, ?, ?, 'UNLV', 'UNLV', 'vs', 'W 2-1', 'San Diego',
                          NULL, 2, 1, 2, 1, 'source-game', 'schedule',
                          'source-game', 'score')
                """,
                (
                    ("game-one", 1, "2017-03-17"),
                    ("game-two", 2, "2017-03-18"),
                ),
            )
            connection.execute(
                """
                INSERT INTO players(
                    player_id, jersey_number, full_name, position, height, weight,
                    class_year, hometown, high_school, previous_school,
                    source_id, source_locator
                ) VALUES ('alan-trejo', '13', 'Alan Trejo', 'INF', '6-0', '190',
                          'SR', 'Downey, Calif.', 'Warren HS', NULL,
                          'source-game', 'roster')
                """
            )
            connection.execute(
                """
                INSERT INTO staff(
                    staff_id, full_name, title, source_id, source_locator
                ) VALUES ('mark-martinez', 'Mark Martinez', 'Head Coach',
                          'source-game', 'roster')
                """
            )
            connection.execute(
                """
                INSERT INTO schedule_groups(
                    group_id, group_type, label, opponent, start_date, end_date,
                    sdsu_wins, sdsu_losses, source_id, source_locator
                ) VALUES ('unlv-series', 'series', 'UNLV series', 'UNLV',
                          '2017-03-17', '2017-03-18', 2, 0,
                          'source-series', 'embed-html/block[1]')
                """
            )
            connection.executemany(
                """
                INSERT INTO schedule_group_games(
                    group_id, game_id, group_order, source_id, source_locator
                ) VALUES ('unlv-series', ?, ?, 'source-game', ?)
                """,
                (("game-one", 1, "member[1]"), ("game-two", 2, "member[2]")),
            )
            connection.executemany(
                """
                INSERT INTO article_passages(
                    source_id, passage_order, text, source_locator, block_type
                ) VALUES (?, ?, ?, ?, 'narrative')
                """,
                (
                    ("source-game", 1, "Alan Trejo homered against UNLV.", "embed-html/block[1]"),
                    ("source-game", 2, "Mark Martinez addressed the club.", "embed-html/block[2]"),
                    ("source-series", 1, "The UNLV series overview.", "embed-html/block[1]"),
                    (
                        "source-honor",
                        1,
                        "Alan Trejo was named Player of the Week.",
                        "embed-html/block[1]",
                    ),
                ),
            )
            connection.executemany(
                """
                INSERT INTO article_passage_games(
                    source_id, passage_order, game_id, relationship
                ) VALUES (?, ?, ?, 'recap')
                """,
                (
                    ("source-game", 1, "game-one"),
                    ("source-game", 2, "game-one"),
                ),
            )
            connection.executemany(
                """
                INSERT INTO article_passage_players(
                    source_id, passage_order, player_id, match_kind
                ) VALUES (?, 1, 'alan-trejo', 'full_name')
                """,
                (("source-game",), ("source-honor",)),
            )
            connection.execute(
                """
                INSERT INTO article_passage_staff(
                    source_id, passage_order, staff_id, match_kind
                ) VALUES ('source-game', 2, 'mark-martinez', 'exact_full_name')
                """
            )
            connection.execute(
                """
                INSERT INTO schedule_group_sources(group_id, source_id, relationship)
                VALUES ('unlv-series', 'source-series', 'series_context')
                """
            )
            connection.execute(
                """
                INSERT INTO season_narrative_sources(season, source_id, relationship)
                VALUES (2017, 'source-honor', 'honor')
                """
            )
            connection.execute(
                """
                INSERT INTO play_by_play(
                    game_id, sequence, inning, batting_team, text,
                    source_id, source_locator
                ) VALUES ('game-one', 1, 1, 'San Diego State',
                          'TREJO homered to left field.', 'source-game', 'GAME.PLY[1]')
                """
            )
            connection.execute(
                """
                INSERT INTO play_by_play_players(
                    game_id, sequence, player_id, match_kind
                ) VALUES ('game-one', 1, 'alan-trejo', 'game_scoped_token')
                """
            )
            connection.execute(
                """
                INSERT INTO article_passages_fts(rowid, text)
                SELECT rowid, text FROM article_passages
                """
            )
            connection.execute(
                """
                INSERT INTO play_by_play_fts(rowid, text)
                SELECT rowid, text FROM play_by_play
                """
            )

    def test_entity_first_article_retrieval_and_provenance(self) -> None:
        rows = retrieve_article_passages(
            self.database,
            game_id="game-one",
            player_id="alan-trejo",
            terms=("homered",),
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_locator"], "embed-html/block[1]")
        self.assertEqual(rows[0]["linked_game_ids"], "game-one")
        self.assertEqual(rows[0]["linked_player_ids"], "alan-trejo")
        self.assertEqual(rows[0]["game_relationships"], "game-one:recap")
        self.assertEqual(rows[0]["player_match_kinds"], "alan-trejo:full_name")
        self.assertEqual(rows[0]["original_url"], "https://example.test/game")

    def test_series_combines_direct_and_member_game_evidence(self) -> None:
        rows = retrieve_article_passages(self.database, group_id="unlv-series")
        self.assertEqual(
            [(row["source_id"], row["passage_order"]) for row in rows],
            [("source-game", 1), ("source-game", 2), ("source-series", 1)],
        )

    def test_series_without_direct_source_uses_member_game_evidence(self) -> None:
        with sqlite3.connect(self.database) as connection:
            connection.execute("DELETE FROM schedule_group_sources")
        rows = retrieve_article_passages(self.database, group_id="unlv-series")
        self.assertEqual(
            [(row["source_id"], row["passage_order"]) for row in rows],
            [("source-game", 1), ("source-game", 2)],
        )

    def test_season_honor_staff_opponent_and_play_by_play(self) -> None:
        honor = retrieve_article_passages(
            self.database, season=2017, player_id="alan-trejo"
        )
        staff = retrieve_article_passages(self.database, staff_id="mark-martinez")
        opponent = retrieve_article_passages(
            self.database, opponent="UNLV", terms=("overview",)
        )
        play = retrieve_play_by_play_passages(
            self.database, player_id="alan-trejo", terms=("homered",)
        )
        self.assertEqual([row["source_id"] for row in honor], ["source-honor"])
        self.assertEqual([row["passage_order"] for row in staff], [2])
        self.assertEqual([row["source_id"] for row in opponent], ["source-series"])
        self.assertEqual([(row["game_id"], row["sequence"]) for row in play], [("game-one", 1)])

    def test_unsupported_and_ambiguous_requests_fail_safely(self) -> None:
        self.assertEqual(
            retrieve_article_passages(
                self.database, game_id="game-two", terms=("homered",)
            ),
            [],
        )
        self.assertEqual(
            retrieve_article_passages(
                self.database, game_id="game-one", terms=("Trejo OR overview",)
            ),
            [],
        )
        with self.assertRaises(QueryError):
            retrieve_article_passages(self.database, terms=("homered",))
        with self.assertRaises(QueryError):
            retrieve_article_passages(self.database, game_id="unknown")
        with self.assertRaises(QueryError):
            retrieve_article_passages(self.database, player_id="Alan Trejo")
        with self.assertRaises(QueryError):
            retrieve_article_passages(self.database, opponent="unlv")
        with self.assertRaises(QueryError):
            retrieve_article_passages(self.database, game_id="game-one", terms=("!",))
        with self.assertRaises(QueryError):
            retrieve_play_by_play_passages(self.database, terms=("homered",))


@unittest.skipUnless(_raw_corpus_is_present(), "preserved full corpus is not present")
class LocalNarrativeCorpusTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.database = Path(cls.temporary.name) / "2017.sqlite3"
        build_corpus(ROOT, cls.database)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_representative_entity_and_context_retrieval(self) -> None:
        cases = (
            retrieve_article_passages(
                self.database, player_id="alan-trejo", terms=("home run",)
            ),
            retrieve_article_passages(self.database, game_id="2017-04-15-unlv"),
            retrieve_article_passages(
                self.database,
                game_id="2017-02-25-seton-hall",
                terms=("Seton Hall",),
            ),
            retrieve_article_passages(
                self.database,
                group_id="series-2017-unlv-home",
                terms=("UNLV",),
            ),
            retrieve_article_passages(
                self.database,
                group_id="event-2017-mountain-west-tournament",
                terms=("championship",),
            ),
            retrieve_article_passages(
                self.database,
                group_id="event-2017-ncaa-tournament",
                terms=("regional",),
            ),
            retrieve_article_passages(
                self.database, opponent="UNLV", terms=("UNLV",)
            ),
            retrieve_article_passages(
                self.database,
                season=2017,
                player_id="david-hensley",
                terms=("Player of the Week",),
            ),
            retrieve_play_by_play_passages(
                self.database, player_id="alan-trejo", terms=("homered",)
            ),
        )
        self.assertTrue(all(cases))
        for rows in cases:
            for row in rows:
                self.assertTrue(row["source_id"])
                self.assertTrue(row["source_locator"])
                self.assertTrue(row["original_url"])
                self.assertTrue(row["raw_path"])

    def test_shared_recaps_are_completely_reviewed_and_do_not_leak(self) -> None:
        expected = {
            "2017-02-17-pacific": {3, 4, 5, 6, 7, 11},
            "2017-02-18-pacific": {3, 4, 8, 9, 10, 11},
            "2017-02-25-notre-dame": set(range(3, 11)),
            "2017-02-25-seton-hall": {3, 11, 12, 13, 14},
            "2017-03-25-fresno-state-1": {*range(3, 10), 17},
            "2017-03-25-fresno-state-2": {3, 4, *range(10, 18)},
        }
        for game_id, passage_orders in expected.items():
            shown = show_game(self.database, game_id)["recap_passages"]
            self.assertEqual({row["passage_order"] for row in shown}, passage_orders)
            retrieved = retrieve_article_passages(self.database, game_id=game_id)
            recap_rows = {
                row["passage_order"]
                for row in retrieved
                if game_id in (row["linked_game_ids"] or "").split(",")
                and row["source_id"]
                in {
                    passage["source_id"] for passage in shown
                }
            }
            self.assertEqual(recap_rows, passage_orders)


if __name__ == "__main__":
    unittest.main()
