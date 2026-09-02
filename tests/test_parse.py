from __future__ import annotations

from datetime import date
import gzip
from pathlib import Path
import unittest

from defiance.parse import parse_box_score, parse_recap


FIXTURES = Path(__file__).parent / "fixtures"


class BoxScoreParserTest(unittest.TestCase):
    def setUp(self) -> None:
        self.game = parse_box_score((FIXTURES / "box_score_2017_02_17.html").read_bytes())

    def test_exact_game_and_batting_lines(self) -> None:
        self.assertEqual(self.game.game_id, "2017-02-17-pacific")
        self.assertEqual(self.game.game_date, date(2017, 2, 17))
        self.assertEqual(self.game.opponent, "Pacific")
        self.assertEqual((self.game.sdsu_score, self.game.opponent_score), (11, 5))

        actual = [
            (
                line.player_name,
                line.position,
                line.ab,
                line.r,
                line.h,
                line.rbi,
                line.bb,
                line.so,
                line.po,
                line.a,
                line.lob,
            )
            for line in self.game.batting_lines
        ]
        expected = [
            ("Alan Trejo", "2b", 4, 1, 1, 1, 0, 1, 0, 4, 0),
            ("Danny Sheehan", "ss", 4, 1, 2, 3, 0, 0, 2, 0, 0),
            ("Chase Calabuig", "rf/lf", 3, 1, 0, 1, 1, 0, 2, 0, 1),
            ("Chad Bible", "lf", 3, 0, 1, 0, 1, 2, 1, 0, 0),
            ("Julian Escobedo", "pr/cf", 1, 1, 0, 0, 0, 0, 0, 0, 1),
            ("Jordan Verdon", "1b", 2, 1, 1, 2, 0, 0, 7, 1, 0),
            ("Andrew Martinez", "dh", 4, 0, 2, 1, 0, 0, 0, 0, 0),
            ("Andrew Brown", "3b", 3, 2, 2, 1, 1, 0, 0, 2, 1),
            ("Dean Nevarez", "c", 3, 1, 2, 0, 0, 0, 9, 0, 2),
            ("Hunter Stratton", "c", 0, 1, 0, 0, 1, 0, 2, 0, 0),
            ("Denz'l Chapman", "cf/rf", 2, 1, 1, 1, 1, 0, 3, 1, 0),
            ("David Hensley", "ph/rf", 0, 1, 0, 0, 0, 0, 0, 0, 0),
            ("Brett Seeburger", "p", 0, 0, 0, 0, 0, 0, 0, 1, 0),
            ("Jorge Fernandez", "p", 0, 0, 0, 0, 0, 0, 1, 0, 0),
            ("Adrian Mardueno", "p", 0, 0, 0, 0, 0, 0, 0, 0, 0),
            ("Logan Boyer", "p", 0, 0, 0, 0, 0, 0, 0, 1, 0),
        ]
        self.assertEqual(actual, expected)
        self.assertEqual(
            self.game.batting_totals,
            {"ab": 29, "r": 11, "h": 12, "rbi": 10, "bb": 5, "so": 3, "po": 27, "a": 10, "lob": 5},
        )

    def test_supplemental_batting_values(self) -> None:
        lines = {line.player_name: line for line in self.game.batting_lines}
        self.assertEqual(lines["Andrew Martinez"].doubles, 1)
        self.assertEqual(lines["Jordan Verdon"].triples, 1)
        self.assertEqual(lines["Andrew Brown"].home_runs, 1)
        self.assertEqual(lines["Andrew Brown"].errors, 1)
        self.assertEqual(lines["David Hensley"].hit_by_pitch, 1)
        self.assertEqual(lines["Alan Trejo"].sacrifice_hits, 1)
        self.assertEqual(lines["Jordan Verdon"].sacrifice_flies, 2)
        self.assertEqual(lines["Danny Sheehan"].stolen_bases, 1)
        self.assertEqual(lines["Denz'l Chapman"].caught_stealing, 1)

    def test_exact_pitching_lines_and_outs(self) -> None:
        actual = [
            (
                line.player_name,
                line.decision,
                line.outs,
                line.h,
                line.r,
                line.er,
                line.bb,
                line.so,
                line.wp,
                line.bk,
                line.hbp,
                line.ibb,
                line.ab,
                line.bf,
                line.fo,
                line.go,
                line.np,
            )
            for line in self.game.pitching_lines
        ]
        self.assertEqual(
            actual,
            [
                ("Brett Seeburger", "W,1-0", 17, 5, 4, 1, 3, 6, 0, 0, 1, 0, 23, 27, 6, 5, 95),
                ("Jorge Fernandez", None, 6, 1, 0, 0, 0, 3, 0, 0, 0, 0, 7, 7, 1, 2, 24),
                ("Adrian Mardueno", None, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 2, 2, 0, 1, 3),
                ("Logan Boyer", None, 3, 1, 1, 1, 2, 2, 0, 0, 0, 0, 4, 6, 0, 1, 33),
            ],
        )


class RecapParserTest(unittest.TestCase):
    def test_exact_opener_passages_and_order(self) -> None:
        passages = parse_recap((FIXTURES / "recap_2017_02_17.html").read_bytes())
        self.assertEqual([passage.passage_order for passage in passages], [1, 2, 3])
        self.assertEqual(
            [passage.source_locator for passage in passages],
            ["embed-html/p[5]", "embed-html/p[6]", "embed-html/p[7]"],
        )
        self.assertTrue(passages[0].text.startswith("In the completion for Friday's contest"))
        self.assertIn("final 11-5 score line", passages[0].text)
        self.assertEqual(
            passages[1].text,
            "Four Aztecs ended the game with two hits apiece including Danny Sheehan, Andrew Martinez, Andrew Brown and Dean Nevarez.",
        )
        self.assertTrue(passages[2].text.startswith("Senior starting pitcher Brett Seeburger"))
        self.assertNotIn("Saturday's regularly schedule contest", " ".join(p.text for p in passages))

    def test_gzip_encoded_recap_bytes(self) -> None:
        content = (FIXTURES / "recap_2017_02_17.html").read_bytes()
        self.assertEqual(parse_recap(gzip.compress(content, mtime=0)), parse_recap(content))


if __name__ == "__main__":
    unittest.main()
