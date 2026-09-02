"""Six-table SQLite storage and validation for the Milestone 1 slice."""

from __future__ import annotations

from pathlib import Path
import re
import sqlite3

from .fetch import PreservedSource, sha256_bytes
from .parse import ParsedGame, RecapPassage


class ValidationError(ValueError):
    """Raised when normalized evidence fails Milestone 1 validation."""


SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('box_score', 'recap')),
    original_url TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    raw_path TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS games (
    game_id TEXT PRIMARY KEY,
    game_date TEXT NOT NULL,
    opponent TEXT NOT NULL,
    sdsu_score INTEGER NOT NULL CHECK (sdsu_score >= 0),
    opponent_score INTEGER NOT NULL CHECK (opponent_score >= 0),
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    source_locator TEXT NOT NULL CHECK (length(source_locator) > 0)
);

CREATE TABLE IF NOT EXISTS players (
    player_id TEXT PRIMARY KEY,
    full_name TEXT NOT NULL UNIQUE,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    source_locator TEXT NOT NULL CHECK (length(source_locator) > 0)
);

CREATE TABLE IF NOT EXISTS batting_lines (
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
    doubles INTEGER NOT NULL,
    triples INTEGER NOT NULL,
    home_runs INTEGER NOT NULL,
    hit_by_pitch INTEGER NOT NULL,
    sacrifice_hits INTEGER NOT NULL,
    sacrifice_flies INTEGER NOT NULL,
    stolen_bases INTEGER NOT NULL,
    caught_stealing INTEGER NOT NULL,
    errors INTEGER NOT NULL,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    source_locator TEXT NOT NULL CHECK (length(source_locator) > 0),
    PRIMARY KEY (game_id, player_id)
);

CREATE TABLE IF NOT EXISTS pitching_lines (
    game_id TEXT NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
    player_id TEXT NOT NULL REFERENCES players(player_id),
    decision TEXT,
    outs INTEGER NOT NULL CHECK (outs >= 0),
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
    np INTEGER NOT NULL,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    source_locator TEXT NOT NULL CHECK (length(source_locator) > 0),
    PRIMARY KEY (game_id, player_id)
);

CREATE TABLE IF NOT EXISTS recap_passages (
    game_id TEXT NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
    passage_order INTEGER NOT NULL CHECK (passage_order > 0),
    text TEXT NOT NULL CHECK (length(text) > 0),
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    source_locator TEXT NOT NULL CHECK (length(source_locator) > 0),
    PRIMARY KEY (game_id, passage_order)
);
"""


def _player_id(full_name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", full_name.casefold()).strip("-")


def validate_parsed(game: ParsedGame, passages: tuple[RecapPassage, ...]) -> None:
    if not game.game_id or not game.source_locator:
        raise ValidationError("parsed game is missing its ID or source locator")
    if game.sdsu_score < 0 or game.opponent_score < 0:
        raise ValidationError("game score is invalid")
    if not game.batting_lines:
        raise ValidationError("no SDSU batting lines were parsed")
    if not game.pitching_lines:
        raise ValidationError("no SDSU pitching lines were parsed")
    if not passages:
        raise ValidationError("no February 17 recap passages were parsed")

    batting_names = [line.player_name for line in game.batting_lines]
    pitching_names = [line.player_name for line in game.pitching_lines]
    if len(batting_names) != len(set(batting_names)):
        raise ValidationError("duplicate SDSU batting line")
    if len(pitching_names) != len(set(pitching_names)):
        raise ValidationError("duplicate SDSU pitching line")
    if any(not line.source_locator for line in game.batting_lines):
        raise ValidationError("batting line is missing a source locator")
    if any(not line.source_locator for line in game.pitching_lines):
        raise ValidationError("pitching line is missing a source locator")

    expected_totals = game.batting_totals
    if not expected_totals:
        raise ValidationError("SDSU batting totals are missing")
    for field_name in ("ab", "r", "h", "rbi", "bb", "so", "po", "a", "lob"):
        parsed_total = sum(getattr(line, field_name) for line in game.batting_lines)
        if parsed_total != expected_totals[field_name]:
            raise ValidationError(
                f"SDSU batting {field_name} total mismatch: "
                f"expected {expected_totals[field_name]}, got {parsed_total}"
            )

    if sum(line.outs for line in game.pitching_lines) != 27:
        raise ValidationError("SDSU pitching lines do not total 27 outs")
    if [passage.passage_order for passage in passages] != list(range(1, len(passages) + 1)):
        raise ValidationError("recap passage ordering is invalid")
    if any(not passage.source_locator for passage in passages):
        raise ValidationError("recap passage is missing a source locator")
    if any("Saturday's regularly schedule contest" in passage.text for passage in passages):
        raise ValidationError("February 18 recap content leaked into the selected passages")

    score_match = next(
        (
            re.search(r"final (\d+)-(\d+) score line", passage.text)
            for passage in passages
            if "score line" in passage.text
        ),
        None,
    )
    if score_match is None:
        raise ValidationError("recap does not expose the February 17 final score")
    recap_score = (int(score_match.group(1)), int(score_match.group(2)))
    if recap_score != (game.sdsu_score, game.opponent_score):
        raise ValidationError(
            "box score and recap disagree: "
            f"box={game.sdsu_score}-{game.opponent_score}, "
            f"recap={recap_score[0]}-{recap_score[1]}"
        )


def validate_sources(sources: tuple[PreservedSource, ...]) -> None:
    if len(sources) != 2 or {source.config.kind for source in sources} != {"box_score", "recap"}:
        raise ValidationError("one preserved box score and one preserved recap are required")
    for source in sources:
        if not source.raw_path.is_file():
            raise ValidationError(f"configured raw file is missing: {source.raw_path}")
        actual = sha256_bytes(source.raw_path.read_bytes())
        if actual != source.config.sha256:
            raise ValidationError(
                f"preserved source hash mismatch for {source.config.source_id}"
            )


def create_schema(connection: sqlite3.Connection) -> None:
    for statement in SCHEMA.split(";"):
        if statement.strip():
            connection.execute(statement)


def load_slice(
    database_path: Path,
    game: ParsedGame,
    passages: tuple[RecapPassage, ...],
    sources: tuple[PreservedSource, ...],
    *,
    stored_raw_paths: dict[str, str] | None = None,
) -> None:
    validate_sources(sources)
    validate_parsed(game, passages)
    source_by_kind = {source.config.kind: source for source in sources}
    box_source = source_by_kind["box_score"].config
    recap_source = source_by_kind["recap"].config

    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        connection.execute("BEGIN")
        with connection:
            create_schema(connection)
            for source in sources:
                raw_path = (
                    stored_raw_paths[source.config.source_id]
                    if stored_raw_paths is not None
                    else str(source.raw_path)
                )
                connection.execute(
                    """
                    INSERT INTO sources(source_id, kind, original_url, sha256, raw_path)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(source_id) DO UPDATE SET
                        kind=excluded.kind,
                        original_url=excluded.original_url,
                        sha256=excluded.sha256,
                        raw_path=excluded.raw_path
                    """,
                    (
                        source.config.source_id,
                        source.config.kind,
                        source.config.url,
                        source.config.sha256,
                        raw_path,
                    ),
                )

            connection.execute("DELETE FROM games WHERE game_id = ?", (game.game_id,))
            connection.execute("DELETE FROM players WHERE source_id = ?", (box_source.source_id,))
            connection.execute(
                """
                INSERT INTO games(
                    game_id, game_date, opponent, sdsu_score, opponent_score,
                    source_id, source_locator
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    game.game_id,
                    game.game_date.isoformat(),
                    game.opponent,
                    game.sdsu_score,
                    game.opponent_score,
                    box_source.source_id,
                    game.source_locator,
                ),
            )

            player_locators: dict[str, str] = {}
            for line in (*game.batting_lines, *game.pitching_lines):
                player_locators.setdefault(line.player_name, line.source_locator)
            player_ids = {name: _player_id(name) for name in player_locators}
            if len(player_ids.values()) != len(set(player_ids.values())):
                raise ValidationError("duplicate normalized player IDs")
            connection.executemany(
                """
                INSERT INTO players(player_id, full_name, source_id, source_locator)
                VALUES (?, ?, ?, ?)
                """,
                (
                    (player_ids[name], name, box_source.source_id, locator)
                    for name, locator in player_locators.items()
                ),
            )

            batting_columns = (
                "ab", "r", "h", "rbi", "bb", "so", "po", "a", "lob",
                "doubles", "triples", "home_runs", "hit_by_pitch",
                "sacrifice_hits", "sacrifice_flies", "stolen_bases",
                "caught_stealing", "errors",
            )
            connection.executemany(
                """
                INSERT INTO batting_lines(
                    game_id, player_id, position, ab, r, h, rbi, bb, so, po, a, lob,
                    doubles, triples, home_runs, hit_by_pitch, sacrifice_hits,
                    sacrifice_flies, stolen_bases, caught_stealing, errors,
                    source_id, source_locator
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        game.game_id,
                        player_ids[line.player_name],
                        line.position,
                        *(getattr(line, column) for column in batting_columns),
                        box_source.source_id,
                        line.source_locator,
                    )
                    for line in game.batting_lines
                ),
            )
            connection.executemany(
                """
                INSERT INTO pitching_lines(
                    game_id, player_id, decision, outs, h, r, er, bb, so, wp, bk,
                    hbp, ibb, ab, bf, fo, go, np, source_id, source_locator
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        game.game_id,
                        player_ids[line.player_name],
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
                        box_source.source_id,
                        line.source_locator,
                    )
                    for line in game.pitching_lines
                ),
            )
            connection.executemany(
                """
                INSERT INTO recap_passages(
                    game_id, passage_order, text, source_id, source_locator
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    (
                        game.game_id,
                        passage.passage_order,
                        passage.text,
                        recap_source.source_id,
                        passage.source_locator,
                    )
                    for passage in passages
                ),
            )

            _validate_database(connection, game.game_id)
    finally:
        connection.close()


def _validate_database(connection: sqlite3.Connection, game_id: str) -> None:
    for table in ("games", "players", "batting_lines", "pitching_lines", "recap_passages"):
        missing_source = connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE source_id IS NULL OR source_locator = ''"
        ).fetchone()[0]
        if missing_source:
            raise ValidationError(f"{table} contains rows without valid provenance")

    for table in ("batting_lines", "pitching_lines"):
        unknown_player = connection.execute(
            f"""
            SELECT COUNT(*) FROM {table} AS line
            LEFT JOIN players AS player ON player.player_id = line.player_id
            WHERE line.game_id = ? AND player.player_id IS NULL
            """,
            (game_id,),
        ).fetchone()[0]
        if unknown_player:
            raise ValidationError(f"{table} references an unknown player")

    foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_key_errors:
        raise ValidationError(f"foreign-key check failed: {foreign_key_errors}")
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise ValidationError(f"SQLite integrity check failed: {integrity}")
