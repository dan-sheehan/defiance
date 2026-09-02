"""Normalized SQLite storage and validation for the 2017 SDSU corpus."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3

from .corpus_parse import (
    ArticlePassage,
    ParsedBoxScore,
    ParsedSeasonStatistics,
    RosterPlayer,
    StaffMember,
    person_key,
)
from .db import ValidationError


SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    original_url TEXT NOT NULL,
    sha256 TEXT,
    raw_path TEXT,
    in_scope INTEGER NOT NULL CHECK (in_scope IN (0, 1)),
    status TEXT NOT NULL CHECK (status IN ('available', 'unavailable', 'excluded')),
    classification TEXT NOT NULL,
    title TEXT,
    notes TEXT,
    CHECK (
        (in_scope = 1 AND status = 'available' AND sha256 IS NOT NULL AND raw_path IS NOT NULL)
        OR (status IN ('unavailable', 'excluded') AND sha256 IS NULL AND raw_path IS NULL)
    )
);

CREATE TABLE IF NOT EXISTS source_gaps (
    gap_order INTEGER PRIMARY KEY,
    game_id TEXT REFERENCES games(game_id) DEFERRABLE INITIALLY DEFERRED,
    source_id TEXT REFERENCES sources(source_id),
    kind TEXT NOT NULL,
    reason TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_conflicts (
    conflict_order INTEGER PRIMARY KEY,
    game_id TEXT REFERENCES games(game_id) DEFERRABLE INITIALLY DEFERRED,
    field TEXT NOT NULL,
    source_a_id TEXT NOT NULL REFERENCES sources(source_id),
    source_a_value TEXT NOT NULL,
    source_a_locator TEXT NOT NULL CHECK (length(source_a_locator) > 0),
    source_b_id TEXT NOT NULL REFERENCES sources(source_id),
    source_b_value TEXT NOT NULL,
    source_b_locator TEXT NOT NULL CHECK (length(source_b_locator) > 0),
    resolution TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS games (
    game_id TEXT PRIMARY KEY,
    schedule_order INTEGER NOT NULL UNIQUE CHECK (schedule_order BETWEEN 1 AND 63),
    game_date TEXT NOT NULL,
    opponent TEXT NOT NULL,
    source_opponent TEXT NOT NULL,
    designation TEXT NOT NULL CHECK (designation IN ('at', 'vs')),
    schedule_result TEXT NOT NULL,
    location TEXT NOT NULL,
    tournament TEXT,
    schedule_sdsu_score INTEGER NOT NULL CHECK (schedule_sdsu_score >= 0),
    schedule_opponent_score INTEGER NOT NULL CHECK (schedule_opponent_score >= 0),
    sdsu_score INTEGER NOT NULL CHECK (sdsu_score >= 0),
    opponent_score INTEGER NOT NULL CHECK (opponent_score >= 0),
    schedule_source_id TEXT NOT NULL REFERENCES sources(source_id),
    schedule_source_locator TEXT NOT NULL CHECK (length(schedule_source_locator) > 0),
    score_source_id TEXT NOT NULL REFERENCES sources(source_id),
    score_source_locator TEXT NOT NULL CHECK (length(score_source_locator) > 0)
);

CREATE TABLE IF NOT EXISTS game_sources (
    game_id TEXT NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    relationship TEXT NOT NULL CHECK (relationship IN ('schedule', 'box_score', 'recap')),
    PRIMARY KEY (game_id, source_id, relationship)
);

CREATE TABLE IF NOT EXISTS players (
    player_id TEXT PRIMARY KEY,
    jersey_number TEXT NOT NULL,
    full_name TEXT NOT NULL UNIQUE,
    position TEXT NOT NULL,
    height TEXT NOT NULL,
    weight TEXT NOT NULL,
    class_year TEXT NOT NULL,
    hometown TEXT NOT NULL,
    high_school TEXT NOT NULL,
    previous_school TEXT,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    source_locator TEXT NOT NULL CHECK (length(source_locator) > 0)
);

CREATE TABLE IF NOT EXISTS staff (
    staff_id TEXT PRIMARY KEY,
    full_name TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    source_locator TEXT NOT NULL CHECK (length(source_locator) > 0)
);

CREATE TABLE IF NOT EXISTS season_batting (
    scope TEXT NOT NULL CHECK (scope IN ('overall', 'conference')),
    subject_type TEXT NOT NULL CHECK (subject_type IN ('player', 'team', 'opponents')),
    player_id TEXT REFERENCES players(player_id),
    subject_name TEXT NOT NULL,
    batting_average TEXT,
    games INTEGER NOT NULL,
    starts INTEGER NOT NULL,
    at_bats INTEGER NOT NULL,
    runs INTEGER NOT NULL,
    hits INTEGER NOT NULL,
    doubles INTEGER NOT NULL,
    triples INTEGER NOT NULL,
    home_runs INTEGER NOT NULL,
    runs_batted_in INTEGER NOT NULL,
    total_bases INTEGER NOT NULL,
    slugging_percentage TEXT,
    walks INTEGER NOT NULL,
    hit_by_pitch INTEGER NOT NULL,
    strikeouts INTEGER NOT NULL,
    grounded_into_double_plays INTEGER NOT NULL,
    on_base_percentage TEXT,
    sacrifice_flies INTEGER NOT NULL,
    sacrifice_hits INTEGER NOT NULL,
    stolen_bases INTEGER NOT NULL,
    stolen_base_attempts INTEGER NOT NULL,
    putouts INTEGER NOT NULL,
    assists INTEGER NOT NULL,
    errors INTEGER NOT NULL,
    fielding_percentage TEXT,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    source_locator TEXT NOT NULL CHECK (length(source_locator) > 0),
    PRIMARY KEY (scope, subject_type, subject_name),
    CHECK ((subject_type = 'player') = (player_id IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS season_pitching (
    scope TEXT NOT NULL CHECK (scope IN ('overall', 'conference')),
    subject_type TEXT NOT NULL CHECK (subject_type IN ('player', 'team', 'opponents')),
    player_id TEXT REFERENCES players(player_id),
    subject_name TEXT NOT NULL,
    earned_run_average TEXT,
    wins INTEGER NOT NULL,
    losses INTEGER NOT NULL,
    appearances INTEGER NOT NULL,
    starts INTEGER NOT NULL,
    complete_games INTEGER NOT NULL,
    shutouts INTEGER NOT NULL,
    combined_shutouts INTEGER NOT NULL,
    saves INTEGER NOT NULL,
    outs INTEGER NOT NULL,
    hits INTEGER NOT NULL,
    runs INTEGER NOT NULL,
    earned_runs INTEGER NOT NULL,
    walks INTEGER NOT NULL,
    strikeouts INTEGER NOT NULL,
    doubles_allowed INTEGER NOT NULL,
    triples_allowed INTEGER NOT NULL,
    home_runs_allowed INTEGER NOT NULL,
    at_bats_against INTEGER NOT NULL,
    opponent_batting_average TEXT,
    wild_pitches INTEGER NOT NULL,
    hit_batters INTEGER NOT NULL,
    balks INTEGER NOT NULL,
    sacrifice_flies_allowed INTEGER NOT NULL,
    sacrifice_hits_allowed INTEGER NOT NULL,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    source_locator TEXT NOT NULL CHECK (length(source_locator) > 0),
    PRIMARY KEY (scope, subject_type, subject_name),
    CHECK ((subject_type = 'player') = (player_id IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS season_fielding (
    scope TEXT NOT NULL CHECK (scope IN ('overall', 'conference')),
    subject_type TEXT NOT NULL CHECK (subject_type IN ('player', 'team', 'opponents')),
    player_id TEXT REFERENCES players(player_id),
    subject_name TEXT NOT NULL,
    chances INTEGER NOT NULL,
    putouts INTEGER NOT NULL,
    assists INTEGER NOT NULL,
    errors INTEGER NOT NULL,
    fielding_percentage TEXT,
    double_plays INTEGER NOT NULL,
    stolen_bases_allowed INTEGER NOT NULL,
    caught_stealing INTEGER NOT NULL,
    stolen_base_percentage TEXT,
    passed_balls INTEGER NOT NULL,
    catcher_interference INTEGER NOT NULL,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    source_locator TEXT NOT NULL CHECK (length(source_locator) > 0),
    PRIMARY KEY (scope, subject_type, subject_name),
    CHECK ((subject_type = 'player') = (player_id IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS season_records (
    record_order INTEGER PRIMARY KEY CHECK (record_order > 0),
    label TEXT NOT NULL,
    wins INTEGER NOT NULL,
    losses INTEGER NOT NULL,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    source_locator TEXT NOT NULL CHECK (length(source_locator) > 0)
);

CREATE TABLE IF NOT EXISTS season_inning_runs (
    subject_name TEXT NOT NULL,
    inning_label TEXT NOT NULL,
    runs INTEGER NOT NULL,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    source_locator TEXT NOT NULL CHECK (length(source_locator) > 0),
    PRIMARY KEY (subject_name, inning_label)
);

CREATE TABLE IF NOT EXISTS season_stat_notes (
    scope TEXT NOT NULL CHECK (scope IN ('overall', 'conference')),
    note_order INTEGER NOT NULL,
    text TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    source_locator TEXT NOT NULL CHECK (length(source_locator) > 0),
    PRIMARY KEY (scope, note_order)
);

CREATE TABLE IF NOT EXISTS game_batting (
    game_id TEXT NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
    player_id TEXT NOT NULL REFERENCES players(player_id),
    position TEXT NOT NULL,
    ab INTEGER NOT NULL,
    r INTEGER NOT NULL,
    h INTEGER NOT NULL,
    rbi INTEGER NOT NULL,
    bb INTEGER NOT NULL,
    so INTEGER NOT NULL,
    po INTEGER NOT NULL,
    a INTEGER NOT NULL,
    lob INTEGER NOT NULL,
    doubles INTEGER,
    triples INTEGER,
    home_runs INTEGER,
    hit_by_pitch INTEGER,
    sacrifice_hits INTEGER,
    sacrifice_flies INTEGER,
    stolen_bases INTEGER,
    caught_stealing INTEGER,
    errors INTEGER,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    source_locator TEXT NOT NULL CHECK (length(source_locator) > 0),
    PRIMARY KEY (game_id, player_id)
);

CREATE TABLE IF NOT EXISTS game_pitching (
    game_id TEXT NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
    player_id TEXT NOT NULL REFERENCES players(player_id),
    decision TEXT,
    outs INTEGER NOT NULL,
    h INTEGER NOT NULL,
    r INTEGER NOT NULL,
    er INTEGER NOT NULL,
    bb INTEGER NOT NULL,
    so INTEGER NOT NULL,
    wp INTEGER NOT NULL,
    bk INTEGER NOT NULL,
    hbp INTEGER NOT NULL,
    ibb INTEGER NOT NULL,
    ab INTEGER NOT NULL,
    bf INTEGER NOT NULL,
    fo INTEGER NOT NULL,
    go INTEGER NOT NULL,
    np INTEGER,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    source_locator TEXT NOT NULL CHECK (length(source_locator) > 0),
    PRIMARY KEY (game_id, player_id)
);

CREATE TABLE IF NOT EXISTS play_by_play (
    game_id TEXT NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL CHECK (sequence > 0),
    inning INTEGER NOT NULL CHECK (inning > 0),
    batting_team TEXT NOT NULL,
    text TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    source_locator TEXT NOT NULL CHECK (length(source_locator) > 0),
    PRIMARY KEY (game_id, sequence)
);

CREATE TABLE IF NOT EXISTS article_passages (
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    passage_order INTEGER NOT NULL CHECK (passage_order > 0),
    text TEXT NOT NULL,
    source_locator TEXT NOT NULL CHECK (length(source_locator) > 0),
    PRIMARY KEY (source_id, passage_order)
);
"""


@dataclass(frozen=True)
class CorpusData:
    manifest: dict[str, object]
    players: tuple[RosterPlayer, ...]
    staff: tuple[StaffMember, ...]
    season_statistics: ParsedSeasonStatistics
    box_scores: dict[str, ParsedBoxScore]
    articles: dict[str, tuple[ArticlePassage, ...]]


def _schedule_score(result: str) -> tuple[int, int]:
    match = re.fullmatch(r"[WL]\s+(\d+)-(\d+)", result)
    if not match:
        raise ValidationError(f"invalid schedule result: {result!r}")
    return int(match.group(1)), int(match.group(2))


def _known_score_conflicts(manifest: dict[str, object]) -> set[tuple[str, str, str]]:
    conflicts = manifest.get("known_conflicts")
    if not isinstance(conflicts, list):
        raise ValidationError("manifest known_conflicts must be a list")
    return {
        (
            str(conflict["game_id"]),
            str(conflict["source_a_value"]),
            str(conflict["source_b_value"]),
        )
        for conflict in conflicts
        if isinstance(conflict, dict) and conflict.get("field") == "final_score"
    }


def validate_corpus_data(data: CorpusData) -> None:
    manifest = data.manifest
    sources = manifest.get("sources")
    games = manifest.get("games")
    gaps = manifest.get("known_gaps")
    if not isinstance(sources, list) or len(sources) != 248:
        raise ValidationError("corpus inventory must contain 248 discovered sources")
    if not isinstance(games, list) or len(games) != 63:
        raise ValidationError("corpus must contain 63 scheduled games")
    if not isinstance(gaps, list):
        raise ValidationError("corpus inventory is missing known gaps")

    source_ids = [str(source["source_id"]) for source in sources]
    if len(source_ids) != len(set(source_ids)):
        raise ValidationError("corpus inventory contains duplicate source IDs")
    source_id_set = set(source_ids)
    game_ids = {str(game["game_id"]) for game in games}
    if len(game_ids) != len(games):
        raise ValidationError("corpus inventory contains duplicate game IDs")
    for game in games:
        for field in ("schedule_source_id", "recap_source_id"):
            if str(game[field]) not in source_id_set:
                raise ValidationError(f"{game['game_id']} references unknown {field}")
        box_source_id = game["box_score_source_id"]
        if box_source_id and str(box_source_id) not in source_id_set:
            raise ValidationError(
                f"{game['game_id']} references unknown box_score_source_id"
            )
    for gap in gaps:
        if gap.get("game_id") and str(gap["game_id"]) not in game_ids:
            raise ValidationError(f"gap references unknown game {gap['game_id']}")
        if gap.get("source_id") and str(gap["source_id"]) not in source_id_set:
            raise ValidationError(f"gap references unknown source {gap['source_id']}")
    conflicts = manifest.get("known_conflicts")
    if not isinstance(conflicts, list):
        raise ValidationError("corpus inventory is missing known conflicts")
    for conflict in conflicts:
        if conflict.get("game_id") and str(conflict["game_id"]) not in game_ids:
            raise ValidationError(
                f"conflict references unknown game {conflict['game_id']}"
            )
        for field in ("source_a_id", "source_b_id"):
            if str(conflict[field]) not in source_id_set:
                raise ValidationError(f"conflict references unknown {field}")
        for field in ("source_a_locator", "source_b_locator", "resolution"):
            if not conflict.get(field):
                raise ValidationError(f"conflict is missing {field}")
    available_in_scope = [
        source
        for source in sources
        if source["in_scope"] and source["status"] == "available"
    ]
    if len(available_in_scope) != 225:
        raise ValidationError(
            f"expected 225 preserved in-scope sources, found {len(available_in_scope)}"
        )
    if len(data.players) != 33 or len(data.staff) != 7:
        raise ValidationError(
            f"unexpected roster coverage: players={len(data.players)}, staff={len(data.staff)}"
        )
    player_by_key = {person_key(player.full_name): player for player in data.players}
    if len(player_by_key) != len(data.players):
        raise ValidationError("roster contains duplicate normalized player names")

    stats = data.season_statistics
    for rows in (stats.batting, stats.pitching, stats.fielding):
        keys: set[tuple[str, str, str]] = set()
        for row in rows:
            key = (row.scope, row.subject_type, row.subject_name)
            if key in keys:
                raise ValidationError(f"duplicate season-statistics row: {key}")
            keys.add(key)
            if row.subject_type == "player" and person_key(row.subject_name) not in player_by_key:
                raise ValidationError(
                    f"season-statistics row references unknown player: {row.subject_name}"
                )

    if set(data.box_scores) != {
        str(game["game_id"]) for game in games if game["box_score_source_id"]
    }:
        raise ValidationError("parsed box-score coverage does not match the inventory")
    if len(data.box_scores) != 60:
        raise ValidationError(f"expected 60 parsed box scores, found {len(data.box_scores)}")

    actual_score_conflicts: set[tuple[str, str, str]] = set()
    total_sdsu_runs = 0
    total_opponent_runs = 0
    wins = 0
    losses = 0
    pbp_games = 0
    for game in games:
        game_id = str(game["game_id"])
        schedule_score = _schedule_score(str(game["result"]))
        box = data.box_scores.get(game_id)
        if box is None:
            canonical_score = schedule_score
        else:
            canonical_score = (box.sdsu_score, box.opponent_score)
            if canonical_score != schedule_score:
                actual_score_conflicts.add(
                    (
                        game_id,
                        f"{schedule_score[0]}-{schedule_score[1]}",
                        f"{canonical_score[0]}-{canonical_score[1]}",
                    )
                )
            batting_names = [line.player_name for line in box.batting_lines]
            pitching_names = [line.player_name for line in box.pitching_lines]
            if len(batting_names) != len(set(map(person_key, batting_names))):
                raise ValidationError(f"{game_id} contains duplicate batting lines")
            if len(pitching_names) != len(set(map(person_key, pitching_names))):
                raise ValidationError(f"{game_id} contains duplicate pitching lines")
            for name in (*batting_names, *pitching_names):
                if person_key(name) not in player_by_key:
                    raise ValidationError(f"{game_id} references unknown player {name}")
            for column in ("ab", "r", "h", "rbi", "bb", "so", "po", "a"):
                parsed_total = sum(int(line.values[column]) for line in box.batting_lines)
                if parsed_total != box.batting_totals[column]:
                    raise ValidationError(
                        f"{game_id} batting {column} mismatch: "
                        f"source={box.batting_totals[column]}, rows={parsed_total}"
                    )
            pitching_outs = sum(int(line.values["outs"]) for line in box.pitching_lines)
            if pitching_outs != box.batting_totals["po"]:
                raise ValidationError(
                    f"{game_id} pitching outs {pitching_outs} do not match "
                    f"team putouts {box.batting_totals['po']}"
                )
            has_pbp = bool(box.play_by_play)
            if has_pbp != bool(game["play_by_play_available"]):
                raise ValidationError(f"{game_id} play-by-play availability mismatch")
            if has_pbp:
                pbp_games += 1
                if [play.sequence for play in box.play_by_play] != list(
                    range(1, len(box.play_by_play) + 1)
                ):
                    raise ValidationError(f"{game_id} play-by-play ordering is invalid")

        total_sdsu_runs += canonical_score[0]
        total_opponent_runs += canonical_score[1]
        wins += canonical_score[0] > canonical_score[1]
        losses += canonical_score[0] < canonical_score[1]

    expected_score_conflicts = _known_score_conflicts(manifest)
    if actual_score_conflicts != expected_score_conflicts:
        raise ValidationError(
            "score conflicts differ from reviewed inventory: "
            f"expected={sorted(expected_score_conflicts)}, "
            f"actual={sorted(actual_score_conflicts)}"
        )
    if (total_sdsu_runs, total_opponent_runs, wins, losses) != (421, 298, 42, 21):
        raise ValidationError(
            "canonical game totals disagree with final season statistics: "
            f"runs={total_sdsu_runs}-{total_opponent_runs}, record={wins}-{losses}"
        )
    if pbp_games != 43:
        raise ValidationError(f"expected play-by-play for 43 games, found {pbp_games}")

    overall_team_batting = next(
        row
        for row in stats.batting
        if row.scope == "overall" and row.subject_type == "team"
    )
    overall_team_pitching = next(
        row
        for row in stats.pitching
        if row.scope == "overall" and row.subject_type == "team"
    )
    overall_record = next(row for row in stats.records if row.label == "Overall")
    if (
        overall_team_batting.values["runs"],
        overall_team_pitching.values["runs"],
        overall_record.wins,
        overall_record.losses,
    ) != (421, 298, 42, 21):
        raise ValidationError("parsed final season totals are inconsistent")
    if overall_team_batting.values["putouts"] != overall_team_pitching.values["outs"]:
        raise ValidationError("season fielding putouts and pitching outs disagree")

    expected_article_sources = {
        str(source["source_id"])
        for source in sources
        if source["in_scope"]
        and source["status"] == "available"
        and source["kind"] in {"recap", "news_article", "postseason_hub"}
    }
    if set(data.articles) != expected_article_sources:
        raise ValidationError("article passage coverage does not match the inventory")
    if any(not passages for passages in data.articles.values()):
        raise ValidationError("an in-scope narrative source produced no passages")


def _player_id_map(players: tuple[RosterPlayer, ...]) -> dict[str, str]:
    return {person_key(player.full_name): player.player_id for player in players}


def _clear_tables(connection: sqlite3.Connection) -> None:
    tables = (
        "article_passages",
        "play_by_play",
        "game_pitching",
        "game_batting",
        "season_stat_notes",
        "season_inning_runs",
        "season_records",
        "season_fielding",
        "season_pitching",
        "season_batting",
        "staff",
        "players",
        "game_sources",
        "games",
        "source_conflicts",
        "source_gaps",
        "sources",
    )
    for table in tables:
        connection.execute(f"DELETE FROM {table}")


def _insert_season_rows(
    connection: sqlite3.Connection,
    table: str,
    rows: tuple,
    value_columns: tuple[str, ...],
    player_ids: dict[str, str],
) -> None:
    columns = (
        "scope",
        "subject_type",
        "player_id",
        "subject_name",
        *value_columns,
        "source_id",
        "source_locator",
    )
    placeholders = ", ".join("?" for _ in columns)
    connection.executemany(
        f"INSERT INTO {table}({', '.join(columns)}) VALUES ({placeholders})",
        (
            (
                row.scope,
                row.subject_type,
                player_ids.get(person_key(row.subject_name))
                if row.subject_type == "player"
                else None,
                row.subject_name,
                *(row.values[column] for column in value_columns),
                "sdsu-2017-season-statistics",
                row.source_locator,
            )
            for row in rows
        ),
    )


def load_corpus(database_path: Path, data: CorpusData) -> None:
    validate_corpus_data(data)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with connection:
            connection.executescript(SCHEMA)
            _clear_tables(connection)
            sources = data.manifest["sources"]
            games = data.manifest["games"]
            gaps = data.manifest["known_gaps"]
            conflicts = data.manifest["known_conflicts"]
            assert isinstance(sources, list)
            assert isinstance(games, list)
            assert isinstance(gaps, list)
            assert isinstance(conflicts, list)

            connection.executemany(
                """
                INSERT INTO sources(
                    source_id, kind, original_url, sha256, raw_path, in_scope,
                    status, classification, title, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        source["source_id"],
                        source["kind"],
                        source["url"],
                        source["sha256"],
                        source["raw_path"],
                        int(bool(source["in_scope"])),
                        source["status"],
                        source["classification"],
                        source["title"],
                        source["notes"],
                    )
                    for source in sources
                ),
            )
            connection.executemany(
                """
                INSERT INTO source_gaps(gap_order, game_id, source_id, kind, reason)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    (
                        order,
                        gap.get("game_id"),
                        gap.get("source_id"),
                        gap["kind"],
                        gap["reason"],
                    )
                    for order, gap in enumerate(gaps, start=1)
                ),
            )
            connection.executemany(
                """
                INSERT INTO source_conflicts(
                    conflict_order, game_id, field, source_a_id, source_a_value,
                    source_a_locator, source_b_id, source_b_value,
                    source_b_locator, resolution
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        order,
                        conflict.get("game_id"),
                        conflict["field"],
                        conflict["source_a_id"],
                        conflict["source_a_value"],
                        conflict["source_a_locator"],
                        conflict["source_b_id"],
                        conflict["source_b_value"],
                        conflict["source_b_locator"],
                        conflict["resolution"],
                    )
                    for order, conflict in enumerate(conflicts, start=1)
                ),
            )

            for game in games:
                game_id = str(game["game_id"])
                schedule_sdsu, schedule_opponent = _schedule_score(str(game["result"]))
                schedule_locator = f"schedule/event[{game['schedule_order']}]"
                box = data.box_scores.get(game_id)
                if box:
                    sdsu_score, opponent_score = box.sdsu_score, box.opponent_score
                    score_source_id = str(game["box_score_source_id"])
                    score_locator = box.source_locator
                else:
                    sdsu_score, opponent_score = schedule_sdsu, schedule_opponent
                    score_source_id = str(game["schedule_source_id"])
                    score_locator = schedule_locator
                connection.execute(
                    """
                    INSERT INTO games(
                        game_id, schedule_order, game_date, opponent, source_opponent,
                        designation, schedule_result, location, tournament,
                        schedule_sdsu_score, schedule_opponent_score,
                        sdsu_score, opponent_score, schedule_source_id,
                        schedule_source_locator, score_source_id, score_source_locator
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        game_id,
                        game["schedule_order"],
                        game["game_date"],
                        game["opponent"],
                        game["source_opponent"],
                        game["designation"],
                        game["result"],
                        game["location"],
                        game["tournament"],
                        schedule_sdsu,
                        schedule_opponent,
                        sdsu_score,
                        opponent_score,
                        game["schedule_source_id"],
                        schedule_locator,
                        score_source_id,
                        score_locator,
                    ),
                )
                relationships = [
                    (game_id, game["schedule_source_id"], "schedule"),
                    (game_id, game["recap_source_id"], "recap"),
                ]
                if game["box_score_source_id"]:
                    relationships.append(
                        (game_id, game["box_score_source_id"], "box_score")
                    )
                connection.executemany(
                    """
                    INSERT INTO game_sources(game_id, source_id, relationship)
                    VALUES (?, ?, ?)
                    """,
                    relationships,
                )

            connection.executemany(
                """
                INSERT INTO players(
                    player_id, jersey_number, full_name, position, height, weight,
                    class_year, hometown, high_school, previous_school,
                    source_id, source_locator
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        player.player_id,
                        player.jersey_number,
                        player.full_name,
                        player.position,
                        player.height,
                        player.weight,
                        player.class_year,
                        player.hometown,
                        player.high_school,
                        player.previous_school,
                        "sdsu-2017-roster",
                        player.source_locator,
                    )
                    for player in data.players
                ),
            )
            connection.executemany(
                """
                INSERT INTO staff(staff_id, full_name, title, source_id, source_locator)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    (
                        member.staff_id,
                        member.full_name,
                        member.title,
                        "sdsu-2017-roster",
                        member.source_locator,
                    )
                    for member in data.staff
                ),
            )
            player_ids = _player_id_map(data.players)
            stats = data.season_statistics
            _insert_season_rows(
                connection,
                "season_batting",
                stats.batting,
                (
                    "batting_average",
                    "games",
                    "starts",
                    "at_bats",
                    "runs",
                    "hits",
                    "doubles",
                    "triples",
                    "home_runs",
                    "runs_batted_in",
                    "total_bases",
                    "slugging_percentage",
                    "walks",
                    "hit_by_pitch",
                    "strikeouts",
                    "grounded_into_double_plays",
                    "on_base_percentage",
                    "sacrifice_flies",
                    "sacrifice_hits",
                    "stolen_bases",
                    "stolen_base_attempts",
                    "putouts",
                    "assists",
                    "errors",
                    "fielding_percentage",
                ),
                player_ids,
            )
            _insert_season_rows(
                connection,
                "season_pitching",
                stats.pitching,
                (
                    "earned_run_average",
                    "wins",
                    "losses",
                    "appearances",
                    "starts",
                    "complete_games",
                    "shutouts",
                    "combined_shutouts",
                    "saves",
                    "outs",
                    "hits",
                    "runs",
                    "earned_runs",
                    "walks",
                    "strikeouts",
                    "doubles_allowed",
                    "triples_allowed",
                    "home_runs_allowed",
                    "at_bats_against",
                    "opponent_batting_average",
                    "wild_pitches",
                    "hit_batters",
                    "balks",
                    "sacrifice_flies_allowed",
                    "sacrifice_hits_allowed",
                ),
                player_ids,
            )
            _insert_season_rows(
                connection,
                "season_fielding",
                stats.fielding,
                (
                    "chances",
                    "putouts",
                    "assists",
                    "errors",
                    "fielding_percentage",
                    "double_plays",
                    "stolen_bases_allowed",
                    "caught_stealing",
                    "stolen_base_percentage",
                    "passed_balls",
                    "catcher_interference",
                ),
                player_ids,
            )
            connection.executemany(
                """
                INSERT INTO season_records(
                    record_order, label, wins, losses, source_id, source_locator
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        order,
                        record.label,
                        record.wins,
                        record.losses,
                        "sdsu-2017-season-statistics",
                        record.source_locator,
                    )
                    for order, record in enumerate(stats.records, start=1)
                ),
            )
            connection.executemany(
                """
                INSERT INTO season_inning_runs(
                    subject_name, inning_label, runs, source_id, source_locator
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    (
                        subject,
                        inning,
                        runs,
                        "sdsu-2017-season-statistics",
                        locator,
                    )
                    for subject, inning, runs, locator in stats.inning_runs
                ),
            )
            connection.executemany(
                """
                INSERT INTO season_stat_notes(
                    scope, note_order, text, source_id, source_locator
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    (
                        note.scope,
                        note.note_order,
                        note.text,
                        "sdsu-2017-season-statistics",
                        note.source_locator,
                    )
                    for note in stats.notes
                ),
            )

            batting_columns = (
                "ab",
                "r",
                "h",
                "rbi",
                "bb",
                "so",
                "po",
                "a",
                "lob",
                "doubles",
                "triples",
                "home_runs",
                "hit_by_pitch",
                "sacrifice_hits",
                "sacrifice_flies",
                "stolen_bases",
                "caught_stealing",
                "errors",
            )
            pitching_columns = (
                "outs",
                "h",
                "r",
                "er",
                "bb",
                "so",
                "wp",
                "bk",
                "hbp",
                "ibb",
                "ab",
                "bf",
                "fo",
                "go",
                "np",
            )
            for game_id, box in data.box_scores.items():
                game = next(game for game in games if game["game_id"] == game_id)
                source_id = str(game["box_score_source_id"])
                connection.executemany(
                    f"""
                    INSERT INTO game_batting(
                        game_id, player_id, position, {', '.join(batting_columns)},
                        source_id, source_locator
                    ) VALUES ({', '.join('?' for _ in range(23))})
                    """,
                    (
                        (
                            game_id,
                            player_ids[person_key(line.player_name)],
                            line.position,
                            *(line.values[column] for column in batting_columns),
                            source_id,
                            line.source_locator,
                        )
                        for line in box.batting_lines
                    ),
                )
                connection.executemany(
                    f"""
                    INSERT INTO game_pitching(
                        game_id, player_id, decision, {', '.join(pitching_columns)},
                        source_id, source_locator
                    ) VALUES ({', '.join('?' for _ in range(20))})
                    """,
                    (
                        (
                            game_id,
                            player_ids[person_key(line.player_name)],
                            line.decision,
                            *(line.values[column] for column in pitching_columns),
                            source_id,
                            line.source_locator,
                        )
                        for line in box.pitching_lines
                    ),
                )
                connection.executemany(
                    """
                    INSERT INTO play_by_play(
                        game_id, sequence, inning, batting_team, text,
                        source_id, source_locator
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        (
                            game_id,
                            play.sequence,
                            play.inning,
                            play.batting_team,
                            play.text,
                            source_id,
                            play.source_locator,
                        )
                        for play in box.play_by_play
                    ),
                )

            for source_id, passages in data.articles.items():
                connection.executemany(
                    """
                    INSERT INTO article_passages(
                        source_id, passage_order, text, source_locator
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        (
                            source_id,
                            passage.passage_order,
                            passage.text,
                            passage.source_locator,
                        )
                        for passage in passages
                    ),
                )
            validate_database(connection)
    finally:
        connection.close()


def validate_database(connection: sqlite3.Connection) -> None:
    expected_counts = {
        "sources": 248,
        "source_gaps": 24,
        "source_conflicts": 5,
        "games": 63,
        "players": 33,
        "staff": 7,
        "game_sources": 186,
        "season_batting": 37,
        "season_pitching": 32,
        "season_fielding": 61,
        "season_records": 27,
        "season_inning_runs": 22,
        "season_stat_notes": 4,
        "game_batting": 891,
        "game_pitching": 252,
        "play_by_play": 770,
        "article_passages": 1758,
    }
    for table, expected in expected_counts.items():
        actual = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        if actual != expected:
            raise ValidationError(f"{table} count mismatch: expected {expected}, got {actual}")
    source_statuses = dict(
        connection.execute(
            "SELECT status, COUNT(*) FROM sources GROUP BY status"
        ).fetchall()
    )
    if source_statuses != {"available": 225, "excluded": 22, "unavailable": 1}:
        raise ValidationError(f"source status coverage is invalid: {source_statuses}")
    game_coverage = connection.execute(
        """
        SELECT
            (SELECT COUNT(DISTINCT game_id) FROM game_batting),
            (SELECT COUNT(DISTINCT game_id) FROM game_pitching),
            (SELECT COUNT(DISTINCT game_id) FROM play_by_play)
        """
    ).fetchone()
    if game_coverage != (60, 60, 43):
        raise ValidationError(f"normalized game-source coverage is invalid: {game_coverage}")
    game_totals = connection.execute(
        """
        SELECT SUM(sdsu_score), SUM(opponent_score),
               SUM(sdsu_score > opponent_score),
               SUM(sdsu_score < opponent_score)
        FROM games
        """
    ).fetchone()
    if game_totals != (421, 298, 42, 21):
        raise ValidationError(f"normalized game totals are invalid: {game_totals}")
    bad_batting_games = connection.execute(
        """
        SELECT COUNT(*) FROM (
            SELECT games.game_id
            FROM games JOIN game_batting USING (game_id)
            GROUP BY games.game_id, games.sdsu_score
            HAVING SUM(game_batting.r) <> games.sdsu_score
        )
        """
    ).fetchone()[0]
    if bad_batting_games:
        raise ValidationError(
            f"{bad_batting_games} normalized batting totals disagree with game scores"
        )
    bad_pitching_games = connection.execute(
        """
        SELECT COUNT(*) FROM (
            SELECT games.game_id
            FROM games JOIN game_pitching USING (game_id)
            GROUP BY games.game_id, games.opponent_score
            HAVING SUM(game_pitching.r) <> games.opponent_score
        )
        """
    ).fetchone()[0]
    if bad_pitching_games:
        raise ValidationError(
            f"{bad_pitching_games} normalized pitching totals disagree with game scores"
        )
    season_totals = connection.execute(
        """
        SELECT
            (SELECT runs FROM season_batting
             WHERE scope = 'overall' AND subject_type = 'team'),
            (SELECT runs FROM season_pitching
             WHERE scope = 'overall' AND subject_type = 'team'),
            (SELECT wins FROM season_records WHERE label = 'Overall'),
            (SELECT losses FROM season_records WHERE label = 'Overall')
        """
    ).fetchone()
    if season_totals != (421, 298, 42, 21):
        raise ValidationError(f"normalized season totals are invalid: {season_totals}")
    for table in (
        "players",
        "staff",
        "season_batting",
        "season_pitching",
        "season_fielding",
        "season_records",
        "season_inning_runs",
        "season_stat_notes",
        "game_batting",
        "game_pitching",
        "play_by_play",
        "article_passages",
    ):
        missing = connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE source_id IS NULL OR source_locator = ''"
        ).fetchone()[0]
        if missing:
            raise ValidationError(f"{table} contains {missing} rows without provenance")
    missing_games = connection.execute(
        """
        SELECT COUNT(*) FROM games
        WHERE schedule_source_id IS NULL
           OR schedule_source_locator = ''
           OR score_source_id IS NULL
           OR score_source_locator = ''
        """
    ).fetchone()[0]
    if missing_games:
        raise ValidationError(f"games contains {missing_games} rows without provenance")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise ValidationError("foreign-key validation failed")
    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise ValidationError("SQLite integrity check failed")
