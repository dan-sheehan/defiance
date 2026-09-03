from __future__ import annotations

from collections import Counter
from copy import deepcopy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from defiance import cli
from defiance.cli import format_game
from defiance.corpus import build_corpus, validate_existing_corpus
from defiance.corpus_db import validate_schedule_groups
from defiance.corpus_inventory import (
    KNOWN_CONFLICTS,
    load_corpus_inventory,
    parse_schedule_events,
    reviewed_schedule_groups,
)
from defiance.corpus_parse import (
    parse_article,
    parse_corpus_box_score,
    parse_roster,
    parse_season_statistics,
)
from defiance.db import ValidationError
from defiance.query import show_game


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
        groups = manifest["schedule_groups"]
        self.assertEqual(manifest["schema_version"], 2)
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
        self.assertEqual(
            Counter(group["group_type"] for group in groups),
            {"series": 14, "event": 3},
        )
        self.assertEqual(sum(len(group["members"]) for group in groups), 51)
        self.assertEqual(groups, reviewed_schedule_groups(games))
        fresno_series = {
            group["group_id"]: [member["game_id"] for member in group["members"]]
            for group in groups
            if group["group_type"] == "series" and group["opponent"] == "Fresno State"
        }
        self.assertEqual(
            fresno_series,
            {
                "series-2017-fresno-state-away": [
                    "2017-03-25-fresno-state-1",
                    "2017-03-25-fresno-state-2",
                    "2017-03-26-fresno-state",
                ],
                "series-2017-fresno-state-home": [
                    "2017-05-18-fresno-state",
                    "2017-05-19-fresno-state",
                    "2017-05-20-fresno-state",
                ],
            },
        )


class CorpusParserTest(unittest.TestCase):
    def test_compact_roster_fixture_is_parsed_offline(self) -> None:
        players, staff = parse_roster(
            (FIXTURES / "roster_2017_compact.html").read_bytes()
        )
        self.assertEqual(
            [(player.player_id, player.jersey_number, player.position) for player in players],
            [("danny-sheehan", "8", "INF"), ("brett-seeburger", "33", "LHP")],
        )
        self.assertEqual(
            [(member.full_name, member.title) for member in staff],
            [("Mark Martinez", "Head Coach")],
        )
        self.assertTrue(all(player.source_locator for player in players))

    def test_compact_schedule_fixture_is_parsed_offline(self) -> None:
        events = parse_schedule_events(
            (FIXTURES / "schedule_2017_compact.html").read_bytes(),
            expected_events=3,
        )
        self.assertEqual(
            [(event.opponent, event.designation, event.result) for event in events],
            [
                ("Fresno State", "at", "W 5-4"),
                ("(3) Fresno State", "vs", "W 18-10"),
                ("(1) New Mexico", "at", "W 9-8"),
            ],
        )
        self.assertIsNone(events[0].tournament)
        self.assertEqual(events[1].tournament, "Mountain West Tournament")
        self.assertEqual(events[2].tournament, "Mountain West Tournament")
        self.assertTrue(events[0].stats_url and events[0].recap_url)

    def test_compact_season_batting_fixture_is_parsed_offline(self) -> None:
        statistics = parse_season_statistics(
            (FIXTURES / "season_statistics_2017_compact.html").read_bytes()
        )
        sheehan = next(
            row
            for row in statistics.batting
            if row.scope == "overall" and row.subject_name == "Danny Sheehan"
        )
        self.assertEqual(sheehan.values["batting_average"], ".344")
        self.assertEqual(sheehan.values["hits"], 86)
        self.assertEqual(sheehan.values["home_runs"], 7)

    def test_compact_season_pitching_fixture_is_parsed_offline(self) -> None:
        statistics = parse_season_statistics(
            (FIXTURES / "season_statistics_2017_compact.html").read_bytes()
        )
        seeburger = next(
            row
            for row in statistics.pitching
            if row.scope == "overall" and row.subject_name == "Brett Seeburger"
        )
        self.assertEqual((seeburger.values["wins"], seeburger.values["losses"]), (10, 3))
        self.assertEqual(seeburger.values["outs"], 280)
        self.assertEqual(seeburger.values["strikeouts"], 69)

    def test_compact_team_facts_fixture_is_parsed_offline(self) -> None:
        statistics = parse_season_statistics(
            (FIXTURES / "season_statistics_2017_compact.html").read_bytes()
        )
        team_batting = next(
            row
            for row in statistics.batting
            if row.scope == "overall" and row.subject_type == "team"
        )
        team_pitching = next(
            row
            for row in statistics.pitching
            if row.scope == "overall" and row.subject_type == "team"
        )
        records = {record.label: (record.wins, record.losses) for record in statistics.records}
        inning_runs = {
            (subject, inning): runs
            for subject, inning, runs, _ in statistics.inning_runs
        }
        self.assertEqual((team_batting.values["runs"], team_pitching.values["runs"]), (421, 298))
        self.assertEqual(records["Overall"], (42, 21))
        self.assertEqual(records["Conference"], (20, 10))
        self.assertEqual(inning_runs[("San Diego State", "Total")], 421)

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
        self.assertEqual(passages[0].block_type, "dateline")
        self.assertEqual(passages[1].block_type, "resource_link")
        self.assertTrue(
            all(passage.block_type == "narrative" for passage in passages[2:])
        )


class ScheduleGroupingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = load_corpus_inventory(MANIFEST)
        self.schedule_scores = {}
        for game in self.manifest["games"]:
            sdsu_score, opponent_score = game["result"].split()[1].split("-")
            self.schedule_scores[game["game_id"]] = (
                int(sdsu_score),
                int(opponent_score),
            )

    def test_series_and_event_results_are_reconciled_from_games(self) -> None:
        results = validate_schedule_groups(self.manifest, self.schedule_scores)
        self.assertEqual(
            results["series-2017-fresno-state-away"],
            ("2017-03-25", "2017-03-26", 2, 1),
        )
        self.assertEqual(
            results["series-2017-fresno-state-home"],
            ("2017-05-18", "2017-05-20", 1, 2),
        )
        self.assertEqual(
            results["event-2017-mountain-west-tournament"],
            ("2017-05-25", "2017-05-28", 3, 1),
        )

        changed_scores = dict(self.schedule_scores)
        changed_scores["2017-05-20-fresno-state"] = (12, 11)
        changed = validate_schedule_groups(self.manifest, changed_scores)
        self.assertEqual(changed["series-2017-fresno-state-home"][2:], (2, 1))

    def test_duplicate_or_unordered_membership_is_rejected(self) -> None:
        altered = deepcopy(self.manifest)
        altered["schedule_groups"][0]["members"][1]["group_order"] = 1
        with self.assertRaises(ValidationError):
            validate_schedule_groups(altered, self.schedule_scores)

        altered = deepcopy(self.manifest)
        members = altered["schedule_groups"][0]["members"]
        members[1]["game_id"] = members[0]["game_id"]
        with self.assertRaises(ValidationError):
            validate_schedule_groups(altered, self.schedule_scores)


class CorpusCliTest(unittest.TestCase):
    def test_show_game_uses_full_corpus_database(self) -> None:
        game_id = "2017-04-15-unlv"
        with (
            patch.object(cli, "show_game") as query,
            patch.object(cli, "format_game", return_value="rendered"),
            redirect_stdout(io.StringIO()),
        ):
            status = cli.main(["show-game", game_id])

        self.assertEqual(status, 0)
        query.assert_called_once_with(cli.FULL_DATABASE_PATH, game_id)


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

            game = show_game(database, "2017-04-15-unlv")
            self.assertEqual(game["game"]["opponent"], "UNLV")
            self.assertEqual(
                (game["game"]["sdsu_score"], game["game"]["opponent_score"]),
                (16, 3),
            )
            self.assertEqual(len(game["batting"]), 15)
            self.assertEqual(len(game["pitching"]), 3)
            self.assertEqual(len(game["recap_passages"]), 10)
            rendered = format_game(game)
            self.assertIn("Game: 2017-04-15 vs. UNLV", rendered)
            self.assertIn("Final: San Diego State 16, UNLV 3", rendered)
            self.assertIn("SH unknown", rendered)
            self.assertIn("https://goaztecs.com/news/2017/04/15/", rendered)

            with sqlite3.connect(database) as connection:
                counts = {
                    table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    for table in (
                        "sources",
                        "games",
                        "schedule_groups",
                        "schedule_group_games",
                        "players",
                        "game_batting",
                        "game_pitching",
                        "play_by_play",
                        "article_passages",
                        "article_passages_fts",
                        "play_by_play_fts",
                        "article_passage_games",
                        "article_passage_players",
                        "article_passage_staff",
                        "play_by_play_players",
                        "schedule_group_sources",
                        "season_narrative_sources",
                        "source_gaps",
                        "source_conflicts",
                    )
                }
                self.assertEqual(
                    counts,
                    {
                        "sources": 248,
                        "games": 63,
                        "schedule_groups": 17,
                        "schedule_group_games": 51,
                        "players": 33,
                        "game_batting": 891,
                        "game_pitching": 252,
                        "play_by_play": 770,
                        "article_passages": 1758,
                        "article_passages_fts": 1536,
                        "play_by_play_fts": 770,
                        "article_passage_games": 1202,
                        "article_passage_players": 1563,
                        "article_passage_staff": 6,
                        "play_by_play_players": 1810,
                        "schedule_group_sources": 18,
                        "season_narrative_sources": 13,
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
                fresno_series = connection.execute(
                    """
                    SELECT sdsu_wins, sdsu_losses
                    FROM schedule_groups
                    WHERE group_id = 'series-2017-fresno-state-home'
                    """
                ).fetchone()
                self.assertEqual(fresno_series, (1, 2))
                missing_box_rows = connection.execute(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM game_batting
                         WHERE game_id = '2017-05-20-fresno-state'),
                        (SELECT COUNT(*) FROM game_pitching
                         WHERE game_id = '2017-05-20-fresno-state')
                    """
                ).fetchone()
                self.assertEqual(missing_box_rows, (0, 0))

            with sqlite3.connect(database) as connection:
                connection.execute(
                    "UPDATE games SET sdsu_score = 0 WHERE game_id = '2017-04-25-uc-riverside'"
                )
            with self.assertRaises(ValidationError):
                validate_existing_corpus(ROOT, database)


if __name__ == "__main__":
    unittest.main()
