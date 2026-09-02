"""Deterministic SQLite queries for normalized games."""

from __future__ import annotations

from pathlib import Path
import sqlite3


class QueryError(LookupError):
    """Raised when a requested normalized game does not exist."""


def _show_slice_game(
    connection: sqlite3.Connection, game_id: str
) -> dict[str, object]:
    game = connection.execute(
        """
        SELECT game.*, source.original_url, source.raw_path
        FROM games AS game
        JOIN sources AS source ON source.source_id = game.source_id
        WHERE game.game_id = ?
        """,
        (game_id,),
    ).fetchone()
    if game is None:
        raise QueryError(f"unknown game ID: {game_id}")

    batting = connection.execute(
        """
        SELECT line.*, player.full_name, source.original_url, source.raw_path
        FROM batting_lines AS line
        JOIN players AS player ON player.player_id = line.player_id
        JOIN sources AS source ON source.source_id = line.source_id
        WHERE line.game_id = ?
        ORDER BY line.rowid
        """,
        (game_id,),
    ).fetchall()
    pitching = connection.execute(
        """
        SELECT line.*, player.full_name, source.original_url, source.raw_path
        FROM pitching_lines AS line
        JOIN players AS player ON player.player_id = line.player_id
        JOIN sources AS source ON source.source_id = line.source_id
        WHERE line.game_id = ?
        ORDER BY line.rowid
        """,
        (game_id,),
    ).fetchall()
    passages = connection.execute(
        """
        SELECT passage.*, source.original_url, source.raw_path
        FROM recap_passages AS passage
        JOIN sources AS source ON source.source_id = passage.source_id
        WHERE passage.game_id = ?
        ORDER BY passage.passage_order
        """,
        (game_id,),
    ).fetchall()
    return {
        "game": dict(game),
        "batting": [dict(row) for row in batting],
        "pitching": [dict(row) for row in pitching],
        "recap_passages": [dict(row) for row in passages],
    }


def _show_corpus_game(
    connection: sqlite3.Connection, game_id: str
) -> dict[str, object]:
    game = connection.execute(
        """
        SELECT game.game_id, game.game_date, game.opponent,
               game.sdsu_score, game.opponent_score,
               game.score_source_id AS source_id,
               game.score_source_locator AS source_locator,
               source.original_url, source.raw_path
        FROM games AS game
        JOIN sources AS source ON source.source_id = game.score_source_id
        WHERE game.game_id = ?
        """,
        (game_id,),
    ).fetchone()
    if game is None:
        raise QueryError(f"unknown game ID: {game_id}")

    batting = connection.execute(
        """
        SELECT line.*, player.full_name, source.original_url, source.raw_path
        FROM game_batting AS line
        JOIN players AS player ON player.player_id = line.player_id
        JOIN sources AS source ON source.source_id = line.source_id
        WHERE line.game_id = ?
        ORDER BY line.rowid
        """,
        (game_id,),
    ).fetchall()
    pitching = connection.execute(
        """
        SELECT line.*, player.full_name, source.original_url, source.raw_path
        FROM game_pitching AS line
        JOIN players AS player ON player.player_id = line.player_id
        JOIN sources AS source ON source.source_id = line.source_id
        WHERE line.game_id = ?
        ORDER BY line.rowid
        """,
        (game_id,),
    ).fetchall()
    passages = connection.execute(
        """
        SELECT passage.*, source.original_url, source.raw_path
        FROM article_passages AS passage
        JOIN game_sources AS game_source
          ON game_source.source_id = passage.source_id
         AND game_source.relationship = 'recap'
        JOIN sources AS source ON source.source_id = passage.source_id
        WHERE game_source.game_id = ?
        ORDER BY passage.source_id, passage.passage_order
        """,
        (game_id,),
    ).fetchall()
    return {
        "game": dict(game),
        "batting": [dict(row) for row in batting],
        "pitching": [dict(row) for row in pitching],
        "recap_passages": [dict(row) for row in passages],
    }


def show_game(database_path: Path, game_id: str) -> dict[str, object]:
    if not database_path.is_file():
        raise QueryError(f"database does not exist: {database_path}")
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        game_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(games)")
        }
        if "score_source_id" in game_columns:
            return _show_corpus_game(connection, game_id)
        return _show_slice_game(connection, game_id)
    finally:
        connection.close()
