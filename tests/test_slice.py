from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

from defiance.cli import format_game
from defiance.db import ValidationError, load_slice
from defiance.fetch import PreservedSource, SourceConfig, sha256_bytes
from defiance.parse import ParseError, parse_box_score, parse_recap
from defiance.query import show_game


FIXTURES = Path(__file__).parent / "fixtures"
BOX_URL = "https://sandiegost_ftp.sidearmsports.com/custompages/sports/m-basebl/stats/021817aaa.html"
RECAP_URL = "https://goaztecs.com/news/2017/02/18/aztecs-win-halted-game-drop-nightcap-to-pacific"


class OfflineSliceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        box_bytes = (FIXTURES / "box_score_2017_02_17.html").read_bytes()
        recap_bytes = (FIXTURES / "recap_2017_02_17.html").read_bytes()
        box_path = self.root / "box.html"
        recap_path = self.root / "recap.html"
        box_path.write_bytes(box_bytes)
        recap_path.write_bytes(recap_bytes)
        self.sources = (
            PreservedSource(
                SourceConfig("box", "box_score", BOX_URL, sha256_bytes(box_bytes)),
                box_path,
            ),
            PreservedSource(
                SourceConfig("recap", "recap", RECAP_URL, sha256_bytes(recap_bytes)),
                recap_path,
            ),
        )
        self.game = parse_box_score(box_bytes)
        self.passages = parse_recap(recap_bytes)
        self.database = self.root / "slice.sqlite3"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _load(self) -> dict[str, object]:
        load_slice(self.database, self.game, self.passages, self.sources)
        return show_game(self.database, self.game.game_id)

    def test_offline_parse_validate_load_query_and_provenance(self) -> None:
        result = self._load()
        self.assertEqual(result["game"]["game_date"], "2017-02-17")
        self.assertEqual(result["game"]["opponent"], "Pacific")
        self.assertEqual((result["game"]["sdsu_score"], result["game"]["opponent_score"]), (11, 5))
        self.assertEqual(len(result["batting"]), 16)
        self.assertEqual(len(result["pitching"]), 4)
        self.assertEqual(len(result["recap_passages"]), 3)

        all_rows = [result["game"], *result["batting"], *result["pitching"], *result["recap_passages"]]
        for row in all_rows:
            self.assertTrue(row["source_id"])
            self.assertTrue(row["source_locator"])
            self.assertTrue(row["original_url"].startswith("https://"))
            self.assertTrue(row["raw_path"])

        rendered = format_game(result)
        self.assertIn("Final: San Diego State 11, Pacific 5", rendered)
        self.assertIn(BOX_URL, rendered)
        self.assertIn(RECAP_URL, rendered)

        with sqlite3.connect(self.database) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
        self.assertEqual(
            tables,
            {"sources", "games", "players", "batting_lines", "pitching_lines", "recap_passages"},
        )

    def test_second_load_is_idempotent(self) -> None:
        first = self._load()
        second = self._load()
        self.assertEqual(first, second)
        with sqlite3.connect(self.database) as connection:
            counts = {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("sources", "games", "players", "batting_lines", "pitching_lines", "recap_passages")
            }
        self.assertEqual(
            counts,
            {"sources": 2, "games": 1, "players": 16, "batting_lines": 16, "pitching_lines": 4, "recap_passages": 3},
        )

    def test_incomplete_box_fixture_is_rejected(self) -> None:
        content = (FIXTURES / "box_score_2017_02_17.html").read_bytes()
        altered = content.replace(b"San Diego State 11 (1-0)", b"San Diego State")
        with self.assertRaises(ParseError):
            parse_box_score(altered)

    def test_contradictory_recap_score_is_rejected(self) -> None:
        expected = self._load()
        altered_passages = tuple(
            passage.__class__(
                passage.passage_order,
                passage.text.replace("final 11-5 score line", "final 10-5 score line"),
                passage.source_locator,
            )
            for passage in self.passages
        )
        with self.assertRaises(ValidationError):
            load_slice(self.database, self.game, altered_passages, self.sources)
        self.assertEqual(show_game(self.database, self.game.game_id), expected)


if __name__ == "__main__":
    unittest.main()
