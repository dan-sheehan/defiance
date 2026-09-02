from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from defiance.corpus import build_corpus, validate_existing_corpus
from defiance.corpus_inventory import KNOWN_CONFLICTS, load_corpus_inventory
from defiance.corpus_parse import parse_article, parse_corpus_box_score
from defiance.db import ValidationError


ROOT = Path(__file__).parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
MANIFEST = ROOT / "config" / "2017" / "corpus.json"


def _raw_corpus_is_present() -> bool:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return all(
        (ROOT / source["raw_path"]).is_file()
        for source in manifest["sources"]
        if source["in_scope"] and source["status"] == "available"
    )


class CorpusInventoryTest(unittest.TestCase):
    def test_inventory_covers_the_discovered_sdsu_archive(self) -> None:
        manifest = load_corpus_inventory(MANIFEST)
        sources = manifest["sources"]
        games = manifest["games"]
        self.assertEqual(len(sources), 248)
        self.assertEqual(len(games), 63)
        self.assertEqual(Counter(source["status"] for source in sources), {
            "available": 225,
            "excluded": 22,
            "unavailable": 1,
        })
        self.assertEqual(
            Counter(gap["kind"] for gap in manifest["known_gaps"]),
            {"play_by_play": 20, "box_score": 3, "source_unavailable": 1},
        )
        self.assertEqual(manifest["known_conflicts"], KNOWN_CONFLICTS)
        self.assertEqual(
            sum(bool(game["box_score_source_id"]) for game in games),
            60,
        )
        self.assertEqual(
            sum(bool(game["play_by_play_available"]) for game in games),
            43,
        )
        self.assertTrue(all(game["recap_source_id"] for game in games))


class CorpusParserTest(unittest.TestCase):
    def test_np_column_and_full_supplemental_sections_are_parsed(self) -> None:
        box = parse_corpus_box_score(
            (FIXTURES / "box_score_2017_02_17.html").read_bytes(),
            game_id="2017-02-17-pacific",
            opponent="Pacific",
        )
        self.assertEqual((box.sdsu_score, box.opponent_score), (11, 5))
        self.assertEqual(len(box.batting_lines), 16)
        self.assertEqual(len(box.pitching_lines), 4)
        seeburger = next(
            line for line in box.pitching_lines if line.player_name == "Brett Seeburger"
        )
        self.assertEqual(seeburger.values["np"], 95)
        trejo = next(line for line in box.batting_lines if line.player_name == "Alan Trejo")
        self.assertEqual(trejo.values["home_runs"], 0)

    def test_unreported_optional_statistics_remain_null(self) -> None:
        box = parse_corpus_box_score(
            (FIXTURES / "box_score_2017_04_25_no_pbp.html").read_bytes(),
            game_id="2017-04-25-uc-riverside",
            opponent="UC Riverside",
        )
        self.assertEqual((box.sdsu_score, box.opponent_score), (4, 7))
        self.assertFalse(box.play_by_play)
        self.assertTrue(all(line.values["np"] is None for line in box.pitching_lines))
        trejo = next(line for line in box.batting_lines if line.player_name == "Alan Trejo")
        self.assertEqual(trejo.values["triples"], 0)
        self.assertIsNone(trejo.values["home_runs"])
        self.assertIsNone(trejo.values["sacrifice_flies"])
        self.assertIsNone(trejo.values["caught_stealing"])

    def test_extra_inning_play_by_play_is_ordered_and_complete(self) -> None:
        box = parse_corpus_box_score(
            (FIXTURES / "box_score_2017_06_03_extra_innings.html").read_bytes(),
            game_id="2017-06-03-ucla",
            opponent="UCLA",
        )
        self.assertEqual((box.sdsu_score, box.opponent_score), (3, 2))
        self.assertEqual(len(box.play_by_play), 26)
        self.assertEqual(max(play.inning for play in box.play_by_play), 13)
        self.assertEqual(
            [play.sequence for play in box.play_by_play],
            list(range(1, 27)),
        )

    def test_article_blocks_retain_order_and_locators(self) -> None:
        passages = parse_article((FIXTURES / "recap_2017_02_17.html").read_bytes())
        self.assertEqual(len(passages), 8)
        self.assertEqual([passage.passage_order for passage in passages], list(range(1, 9)))
        self.assertEqual(passages[0].text, "Feb. 18, 2017")
        self.assertEqual(passages[0].source_locator, "embed-html/block[1]")


@unittest.skipUnless(_raw_corpus_is_present(), "preserved full corpus is not present")
class LocalFullCorpusTest(unittest.TestCase):
    def test_offline_build_is_idempotent_and_validated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "2017.sqlite3"
            first = build_corpus(ROOT, database)
            second = build_corpus(ROOT, database)
            validated = validate_existing_corpus(ROOT, database)
            self.assertEqual(first, second)
            self.assertEqual(second, validated)

            with sqlite3.connect(database) as connection:
                counts = {
                    table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    for table in (
                        "sources",
                        "games",
                        "players",
                        "game_batting",
                        "game_pitching",
                        "play_by_play",
                        "article_passages",
                        "source_gaps",
                        "source_conflicts",
                    )
                }
                self.assertEqual(
                    counts,
                    {
                        "sources": 248,
                        "games": 63,
                        "players": 33,
                        "game_batting": 891,
                        "game_pitching": 252,
                        "play_by_play": 770,
                        "article_passages": 1758,
                        "source_gaps": 24,
                        "source_conflicts": 5,
                    },
                )
                score = connection.execute(
                    """
                    SELECT schedule_sdsu_score, schedule_opponent_score,
                           sdsu_score, opponent_score
                    FROM games WHERE game_id = '2017-04-25-uc-riverside'
                    """
                ).fetchone()
                self.assertEqual(score, (4, 6, 4, 7))
                unknowns = connection.execute(
                    """
                    SELECT home_runs, sacrifice_flies, caught_stealing
                    FROM game_batting
                    WHERE game_id = '2017-04-25-uc-riverside'
                      AND player_id = 'alan-trejo'
                    """
                ).fetchone()
                self.assertEqual(unknowns, (None, None, None))

            with sqlite3.connect(database) as connection:
                connection.execute(
                    "UPDATE games SET sdsu_score = 0 WHERE game_id = '2017-04-25-uc-riverside'"
                )
            with self.assertRaises(ValidationError):
                validate_existing_corpus(ROOT, database)


if __name__ == "__main__":
    unittest.main()
