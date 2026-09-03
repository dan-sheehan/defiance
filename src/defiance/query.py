"""Deterministic SQLite queries for normalized games."""

from __future__ import annotations

from pathlib import Path
import sqlite3


class QueryError(LookupError):
    """Raised when a structured corpus query is invalid."""


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
        JOIN article_passage_games AS game_source
          ON game_source.source_id = passage.source_id
         AND game_source.passage_order = passage.passage_order
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


def _validate_limit(limit: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise QueryError("limit must be an integer from 1 through 100")


def _fts_query(terms: tuple[str, ...]) -> str | None:
    if not terms:
        return None
    quoted: list[str] = []
    for term in terms:
        if not isinstance(term, str) or not any(character.isalnum() for character in term):
            raise QueryError("search terms must contain letters or numbers")
        quoted.append(f'"{term.strip().replace(chr(34), chr(34) * 2)}"')
    return " AND ".join(quoted)


def _require_value(
    connection: sqlite3.Connection,
    *,
    table: str,
    column: str,
    value: object,
    label: str,
) -> None:
    if connection.execute(
        f"SELECT 1 FROM {table} WHERE {column} = ? LIMIT 1", (value,)
    ).fetchone() is None:
        raise QueryError(f"unknown {label}: {value}")


def retrieve_article_passages(
    database_path: Path,
    *,
    game_id: str | None = None,
    player_id: str | None = None,
    staff_id: str | None = None,
    opponent: str | None = None,
    group_id: str | None = None,
    season: int | None = None,
    terms: tuple[str, ...] = (),
    limit: int = 20,
) -> list[dict[str, object]]:
    """Return article evidence constrained by exact structured selectors."""
    selectors = (game_id, player_id, staff_id, opponent, group_id, season)
    if all(selector is None for selector in selectors):
        raise QueryError("article retrieval requires at least one structured selector")
    _validate_limit(limit)
    search = _fts_query(terms)
    if not database_path.is_file():
        raise QueryError(f"database does not exist: {database_path}")

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        if game_id is not None:
            _require_value(
                connection, table="games", column="game_id", value=game_id, label="game ID"
            )
        if player_id is not None:
            _require_value(
                connection,
                table="players",
                column="player_id",
                value=player_id,
                label="player ID",
            )
        if staff_id is not None:
            _require_value(
                connection, table="staff", column="staff_id", value=staff_id, label="staff ID"
            )
        if opponent is not None:
            _require_value(
                connection,
                table="games",
                column="opponent",
                value=opponent,
                label="canonical opponent",
            )
        if group_id is not None:
            _require_value(
                connection,
                table="schedule_groups",
                column="group_id",
                value=group_id,
                label="schedule group ID",
            )
        if season is not None and season != 2017:
            raise QueryError(f"unknown season: {season}")

        joins = ["JOIN sources AS source ON source.source_id = passage.source_id"]
        conditions = ["passage.block_type IN ('heading', 'narrative')"]
        parameters: list[object] = []
        if search is not None:
            joins.append(
                "JOIN article_passages_fts ON article_passages_fts.rowid = passage.rowid"
            )
            conditions.append("article_passages_fts MATCH ?")
            parameters.append(search)
        if game_id is not None:
            conditions.append(
                """EXISTS (
                    SELECT 1 FROM article_passage_games AS link
                    WHERE link.source_id = passage.source_id
                      AND link.passage_order = passage.passage_order
                      AND link.game_id = ?
                )"""
            )
            parameters.append(game_id)
        if player_id is not None:
            conditions.append(
                """EXISTS (
                    SELECT 1 FROM article_passage_players AS link
                    WHERE link.source_id = passage.source_id
                      AND link.passage_order = passage.passage_order
                      AND link.player_id = ?
                )"""
            )
            parameters.append(player_id)
        if staff_id is not None:
            conditions.append(
                """EXISTS (
                    SELECT 1 FROM article_passage_staff AS link
                    WHERE link.source_id = passage.source_id
                      AND link.passage_order = passage.passage_order
                      AND link.staff_id = ?
                )"""
            )
            parameters.append(staff_id)
        if opponent is not None:
            conditions.append(
                """(
                    EXISTS (
                        SELECT 1
                        FROM article_passage_games AS link
                        JOIN games USING (game_id)
                        WHERE link.source_id = passage.source_id
                          AND link.passage_order = passage.passage_order
                          AND games.opponent = ?
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM schedule_group_sources AS direct
                        JOIN schedule_groups USING (group_id)
                        WHERE direct.source_id = passage.source_id
                          AND schedule_groups.opponent = ?
                    )
                )"""
            )
            parameters.extend((opponent, opponent))
        if group_id is not None:
            conditions.append(
                """(
                    EXISTS (
                        SELECT 1 FROM schedule_group_sources AS direct
                        WHERE direct.source_id = passage.source_id
                          AND direct.group_id = ?
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM article_passage_games AS link
                        JOIN schedule_group_games AS member USING (game_id)
                        WHERE link.source_id = passage.source_id
                          AND link.passage_order = passage.passage_order
                          AND member.group_id = ?
                    )
                )"""
            )
            parameters.extend((group_id, group_id))
        if season is not None:
            conditions.append(
                """EXISTS (
                    SELECT 1 FROM season_narrative_sources AS season_link
                    WHERE season_link.source_id = passage.source_id
                      AND season_link.season = ?
                )"""
            )
            parameters.append(season)

        order = (
            "bm25(article_passages_fts), passage.source_id, passage.passage_order"
            if search is not None
            else "passage.source_id, passage.passage_order"
        )
        parameters.append(limit)
        rows = connection.execute(
            f"""
            SELECT passage.source_id, passage.passage_order, passage.text,
                   passage.source_locator, passage.block_type,
                   source.original_url, source.raw_path, source.title,
                   source.classification,
                   (
                       SELECT group_concat(game_id, ',') FROM (
                           SELECT game_id FROM article_passage_games AS game_link
                           WHERE game_link.source_id = passage.source_id
                             AND game_link.passage_order = passage.passage_order
                           ORDER BY game_id
                       )
                   ) AS linked_game_ids,
                   (
                       SELECT group_concat(player_id, ',') FROM (
                           SELECT player_id FROM article_passage_players AS player_link
                           WHERE player_link.source_id = passage.source_id
                             AND player_link.passage_order = passage.passage_order
                           ORDER BY player_id
                       )
                   ) AS linked_player_ids,
                   (
                       SELECT group_concat(staff_id, ',') FROM (
                           SELECT staff_id FROM article_passage_staff AS staff_link
                           WHERE staff_link.source_id = passage.source_id
                             AND staff_link.passage_order = passage.passage_order
                           ORDER BY staff_id
                       )
                   ) AS linked_staff_ids,
                   (
                       SELECT group_concat(game_id || ':' || relationship, ',') FROM (
                           SELECT game_id, relationship
                           FROM article_passage_games AS game_link
                           WHERE game_link.source_id = passage.source_id
                             AND game_link.passage_order = passage.passage_order
                           ORDER BY game_id, relationship
                       )
                   ) AS game_relationships,
                   (
                       SELECT group_concat(player_id || ':' || match_kind, ',') FROM (
                           SELECT player_id, match_kind
                           FROM article_passage_players AS player_link
                           WHERE player_link.source_id = passage.source_id
                             AND player_link.passage_order = passage.passage_order
                           ORDER BY player_id
                       )
                   ) AS player_match_kinds,
                   (
                       SELECT group_concat(group_id || ':' || relationship, ',') FROM (
                           SELECT group_id, relationship
                           FROM schedule_group_sources AS group_link
                           WHERE group_link.source_id = passage.source_id
                           ORDER BY group_id, relationship
                       )
                   ) AS direct_group_relationships,
                   (
                       SELECT group_concat(season || ':' || relationship, ',') FROM (
                           SELECT season, relationship
                           FROM season_narrative_sources AS season_link
                           WHERE season_link.source_id = passage.source_id
                           ORDER BY season, relationship
                       )
                   ) AS season_relationships
            FROM article_passages AS passage
            {' '.join(joins)}
            WHERE {' AND '.join(conditions)}
            ORDER BY {order}
            LIMIT ?
            """,
            parameters,
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def retrieve_play_by_play_passages(
    database_path: Path,
    *,
    game_id: str | None = None,
    player_id: str | None = None,
    opponent: str | None = None,
    group_id: str | None = None,
    terms: tuple[str, ...] = (),
    limit: int = 20,
) -> list[dict[str, object]]:
    """Return play-by-play evidence separately from article narrative."""
    if all(selector is None for selector in (game_id, player_id, opponent, group_id)):
        raise QueryError("play-by-play retrieval requires a structured selector")
    _validate_limit(limit)
    search = _fts_query(terms)
    if not database_path.is_file():
        raise QueryError(f"database does not exist: {database_path}")

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        if game_id is not None:
            _require_value(
                connection, table="games", column="game_id", value=game_id, label="game ID"
            )
        if player_id is not None:
            _require_value(
                connection,
                table="players",
                column="player_id",
                value=player_id,
                label="player ID",
            )
        if opponent is not None:
            _require_value(
                connection,
                table="games",
                column="opponent",
                value=opponent,
                label="canonical opponent",
            )
        if group_id is not None:
            _require_value(
                connection,
                table="schedule_groups",
                column="group_id",
                value=group_id,
                label="schedule group ID",
            )

        joins = ["JOIN games ON games.game_id = passage.game_id"]
        conditions: list[str] = []
        parameters: list[object] = []
        if search is not None:
            joins.append("JOIN play_by_play_fts ON play_by_play_fts.rowid = passage.rowid")
            conditions.append("play_by_play_fts MATCH ?")
            parameters.append(search)
        if game_id is not None:
            conditions.append("passage.game_id = ?")
            parameters.append(game_id)
        if player_id is not None:
            conditions.append(
                """EXISTS (
                    SELECT 1 FROM play_by_play_players AS player_link
                    WHERE player_link.game_id = passage.game_id
                      AND player_link.sequence = passage.sequence
                      AND player_link.player_id = ?
                )"""
            )
            parameters.append(player_id)
        if opponent is not None:
            conditions.append("games.opponent = ?")
            parameters.append(opponent)
        if group_id is not None:
            conditions.append(
                """EXISTS (
                    SELECT 1 FROM schedule_group_games AS member
                    WHERE member.game_id = passage.game_id
                      AND member.group_id = ?
                )"""
            )
            parameters.append(group_id)
        order = (
            "bm25(play_by_play_fts), games.schedule_order, passage.sequence"
            if search is not None
            else "games.schedule_order, passage.sequence"
        )
        parameters.append(limit)
        rows = connection.execute(
            f"""
            SELECT passage.game_id, passage.sequence, passage.inning,
                   passage.batting_team, passage.text, passage.source_id,
                   passage.source_locator, source.original_url, source.raw_path,
                   (
                       SELECT group_concat(player_id, ',') FROM (
                           SELECT player_id FROM play_by_play_players AS player_link
                           WHERE player_link.game_id = passage.game_id
                             AND player_link.sequence = passage.sequence
                           ORDER BY player_id
                       )
                   ) AS linked_player_ids,
                   (
                       SELECT group_concat(player_id || ':' || match_kind, ',') FROM (
                           SELECT player_id, match_kind
                           FROM play_by_play_players AS player_link
                           WHERE player_link.game_id = passage.game_id
                             AND player_link.sequence = passage.sequence
                           ORDER BY player_id
                       )
                   ) AS player_match_kinds
            FROM play_by_play AS passage
            {' '.join(joins)}
            JOIN sources AS source ON source.source_id = passage.source_id
            WHERE {' AND '.join(conditions) if conditions else '1'}
            ORDER BY {order}
            LIMIT ?
            """,
            parameters,
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()
