"""Deterministic SQLite queries for normalized games."""

from __future__ import annotations

from pathlib import Path
import sqlite3


class QueryError(LookupError):
    """Raised when a structured corpus query is invalid."""


BATTING_LEADER_COLUMNS = frozenset(
    {
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
        "on_base_percentage",
        "stolen_bases",
    }
)
PITCHING_LEADER_COLUMNS = frozenset(
    {
        "earned_run_average",
        "wins",
        "losses",
        "appearances",
        "starts",
        "complete_games",
        "shutouts",
        "saves",
        "outs",
        "hits",
        "runs",
        "earned_runs",
        "walks",
        "strikeouts",
        "home_runs_allowed",
        "opponent_batting_average",
    }
)


def _read_connection(database_path: Path) -> sqlite3.Connection:
    if not database_path.is_file():
        raise QueryError(f"database does not exist: {database_path}")
    try:
        connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    except sqlite3.OperationalError as exc:
        raise QueryError(f"cannot open database: {database_path}") from exc
    connection.row_factory = sqlite3.Row
    return connection


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


def load_question_catalog(database_path: Path) -> dict[str, object]:
    """Load the fixed 2017 entities and scopes used by the question router."""
    connection = _read_connection(database_path)
    try:
        players = connection.execute(
            """
            SELECT player.player_id, player.full_name, player.position,
                   player.source_id, player.source_locator,
                   source.original_url, source.raw_path
            FROM players AS player
            JOIN sources AS source ON source.source_id = player.source_id
            ORDER BY player.full_name
            """
        ).fetchall()
        staff = connection.execute(
            """
            SELECT member.staff_id, member.full_name, member.title,
                   member.source_id, member.source_locator,
                   source.original_url, source.raw_path
            FROM staff AS member
            JOIN sources AS source ON source.source_id = member.source_id
            ORDER BY member.full_name
            """
        ).fetchall()
        games = connection.execute(
            """
            SELECT game.game_id, game.schedule_order, game.game_date,
                   game.opponent, game.designation, game.location,
                   game.tournament, game.sdsu_score, game.opponent_score,
                   game.score_source_id AS source_id,
                   game.score_source_locator AS source_locator,
                   source.original_url, source.raw_path,
                   EXISTS (
                       SELECT 1 FROM game_sources
                       WHERE game_sources.game_id = game.game_id
                         AND game_sources.relationship = 'box_score'
                   ) AS has_box_score
            FROM games AS game
            JOIN sources AS source ON source.source_id = game.score_source_id
            ORDER BY game.schedule_order
            """
        ).fetchall()
        groups = connection.execute(
            """
            SELECT groups.*, source.original_url, source.raw_path
            FROM schedule_groups AS groups
            JOIN sources AS source ON source.source_id = groups.source_id
            ORDER BY groups.start_date, groups.group_id
            """
        ).fetchall()
        memberships = connection.execute(
            """
            SELECT group_id, game_id, group_order, source_id, source_locator
            FROM schedule_group_games
            ORDER BY group_id, group_order
            """
        ).fetchall()
        records = connection.execute(
            """
            SELECT record.*, source.original_url, source.raw_path
            FROM season_records AS record
            JOIN sources AS source ON source.source_id = record.source_id
            ORDER BY record.record_order
            """
        ).fetchall()
        return {
            "players": [dict(row) for row in players],
            "staff": [dict(row) for row in staff],
            "games": [dict(row) for row in games],
            "groups": [dict(row) for row in groups],
            "memberships": [dict(row) for row in memberships],
            "records": [dict(row) for row in records],
        }
    finally:
        connection.close()


def query_player_season(
    database_path: Path,
    player_id: str,
    *,
    scope: str = "overall",
) -> dict[str, object]:
    """Return the player's exact archived season batting and pitching rows."""
    if scope not in {"overall", "conference"}:
        raise QueryError(f"unsupported season scope: {scope}")
    connection = _read_connection(database_path)
    try:
        _require_value(
            connection,
            table="players",
            column="player_id",
            value=player_id,
            label="player ID",
        )
        player = connection.execute(
            """
            SELECT player.player_id, player.full_name, player.position,
                   player.source_id, player.source_locator,
                   source.original_url, source.raw_path
            FROM players AS player
            JOIN sources AS source ON source.source_id = player.source_id
            WHERE player.player_id = ?
            """,
            (player_id,),
        ).fetchone()
        batting = connection.execute(
            """
            SELECT line.*, source.original_url, source.raw_path
            FROM season_batting AS line
            JOIN sources AS source ON source.source_id = line.source_id
            WHERE line.scope = ? AND line.player_id = ?
            """,
            (scope, player_id),
        ).fetchone()
        pitching = connection.execute(
            """
            SELECT line.*, source.original_url, source.raw_path
            FROM season_pitching AS line
            JOIN sources AS source ON source.source_id = line.source_id
            WHERE line.scope = ? AND line.player_id = ?
            """,
            (scope, player_id),
        ).fetchone()
        return {
            "player": dict(player),
            "batting": dict(batting) if batting else None,
            "pitching": dict(pitching) if pitching else None,
        }
    finally:
        connection.close()


def query_player_game(
    database_path: Path,
    player_id: str,
    game_id: str,
) -> dict[str, object]:
    """Return one player's rows for one exact game."""
    connection = _read_connection(database_path)
    try:
        _require_value(
            connection,
            table="players",
            column="player_id",
            value=player_id,
            label="player ID",
        )
        game = connection.execute(
            """
            SELECT game.game_id, game.game_date, game.opponent,
                   game.sdsu_score, game.opponent_score,
                   game.score_source_id AS source_id,
                   game.score_source_locator AS source_locator,
                   source.original_url, source.raw_path,
                   EXISTS (
                       SELECT 1 FROM game_sources
                       WHERE game_sources.game_id = game.game_id
                         AND game_sources.relationship = 'box_score'
                   ) AS has_box_score
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
            SELECT line.*, source.original_url, source.raw_path
            FROM game_batting AS line
            JOIN sources AS source ON source.source_id = line.source_id
            WHERE line.game_id = ? AND line.player_id = ?
            """,
            (game_id, player_id),
        ).fetchone()
        pitching = connection.execute(
            """
            SELECT line.*, source.original_url, source.raw_path
            FROM game_pitching AS line
            JOIN sources AS source ON source.source_id = line.source_id
            WHERE line.game_id = ? AND line.player_id = ?
            """,
            (game_id, player_id),
        ).fetchone()
        return {
            "game": dict(game),
            "batting": dict(batting) if batting else None,
            "pitching": dict(pitching) if pitching else None,
        }
    finally:
        connection.close()


def query_player_aggregate(
    database_path: Path,
    player_id: str,
    *,
    opponent: str | None = None,
    group_id: str | None = None,
) -> dict[str, object]:
    """Aggregate one player across one exact opponent or reviewed group."""
    if (opponent is None) == (group_id is None):
        raise QueryError("player aggregation requires exactly one scope")
    connection = _read_connection(database_path)
    try:
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
            scope_sql = "SELECT game_id FROM games WHERE opponent = ?"
            scope_value = opponent
        else:
            _require_value(
                connection,
                table="schedule_groups",
                column="group_id",
                value=group_id,
                label="schedule group ID",
            )
            scope_sql = "SELECT game_id FROM schedule_group_games WHERE group_id = ?"
            scope_value = group_id

        aggregate = connection.execute(
            f"""
            WITH selected_games AS ({scope_sql})
            SELECT
                COUNT(*) AS selected_games,
                SUM(EXISTS (
                    SELECT 1 FROM game_sources AS source_link
                    WHERE source_link.game_id = selected.game_id
                      AND source_link.relationship = 'box_score'
                )) AS box_games,
                SUM(CASE WHEN batting.player_id IS NOT NULL THEN 1 ELSE 0 END)
                    AS batting_games,
                SUM(COALESCE(batting.ab, 0)) AS batting_ab,
                SUM(COALESCE(batting.r, 0)) AS batting_r,
                SUM(COALESCE(batting.h, 0)) AS batting_h,
                SUM(COALESCE(batting.rbi, 0)) AS batting_rbi,
                SUM(COALESCE(batting.bb, 0)) AS batting_bb,
                SUM(COALESCE(batting.so, 0)) AS batting_so,
                SUM(CASE WHEN batting.player_id IS NOT NULL
                              AND batting.doubles IS NULL THEN 1 ELSE 0 END)
                    AS unknown_doubles,
                SUM(COALESCE(batting.doubles, 0)) AS batting_doubles,
                SUM(CASE WHEN batting.player_id IS NOT NULL
                              AND batting.triples IS NULL THEN 1 ELSE 0 END)
                    AS unknown_triples,
                SUM(COALESCE(batting.triples, 0)) AS batting_triples,
                SUM(CASE WHEN batting.player_id IS NOT NULL
                              AND batting.home_runs IS NULL THEN 1 ELSE 0 END)
                    AS unknown_home_runs,
                SUM(COALESCE(batting.home_runs, 0)) AS batting_home_runs,
                SUM(CASE WHEN batting.player_id IS NOT NULL
                              AND batting.stolen_bases IS NULL THEN 1 ELSE 0 END)
                    AS unknown_stolen_bases,
                SUM(COALESCE(batting.stolen_bases, 0)) AS batting_stolen_bases,
                SUM(CASE WHEN pitching.player_id IS NOT NULL THEN 1 ELSE 0 END)
                    AS pitching_games,
                SUM(COALESCE(pitching.outs, 0)) AS pitching_outs,
                SUM(COALESCE(pitching.h, 0)) AS pitching_h,
                SUM(COALESCE(pitching.r, 0)) AS pitching_r,
                SUM(COALESCE(pitching.er, 0)) AS pitching_er,
                SUM(COALESCE(pitching.bb, 0)) AS pitching_bb,
                SUM(COALESCE(pitching.so, 0)) AS pitching_so,
                SUM(CASE WHEN pitching.decision LIKE 'W,%' THEN 1 ELSE 0 END)
                    AS pitching_wins,
                SUM(CASE WHEN pitching.decision LIKE 'L,%' THEN 1 ELSE 0 END)
                    AS pitching_losses,
                SUM(CASE WHEN pitching.decision LIKE 'S,%' THEN 1 ELSE 0 END)
                    AS pitching_saves,
                SUM(CASE WHEN pitching.player_id IS NOT NULL
                              AND pitching.np IS NULL THEN 1 ELSE 0 END)
                    AS unknown_pitches,
                SUM(COALESCE(pitching.np, 0)) AS pitching_pitches
            FROM selected_games AS selected
            LEFT JOIN game_batting AS batting
              ON batting.game_id = selected.game_id AND batting.player_id = ?
            LEFT JOIN game_pitching AS pitching
              ON pitching.game_id = selected.game_id AND pitching.player_id = ?
            """,
            (scope_value, player_id, player_id),
        ).fetchone()
        games = connection.execute(
            f"""
            WITH selected_games AS ({scope_sql})
            SELECT game.game_id, game.schedule_order, game.game_date,
                   game.opponent, game.sdsu_score, game.opponent_score,
                   game.score_source_id, game.score_source_locator,
                   score_source.original_url AS score_original_url,
                   score_source.raw_path AS score_raw_path,
                   box.source_id AS box_source_id,
                   box_source.original_url AS box_original_url,
                   box_source.raw_path AS box_raw_path,
                   batting.source_locator AS batting_source_locator,
                   pitching.source_locator AS pitching_source_locator
            FROM selected_games AS selected
            JOIN games AS game ON game.game_id = selected.game_id
            JOIN sources AS score_source
              ON score_source.source_id = game.score_source_id
            LEFT JOIN game_sources AS box
              ON box.game_id = game.game_id AND box.relationship = 'box_score'
            LEFT JOIN sources AS box_source ON box_source.source_id = box.source_id
            LEFT JOIN game_batting AS batting
              ON batting.game_id = game.game_id AND batting.player_id = ?
            LEFT JOIN game_pitching AS pitching
              ON pitching.game_id = game.game_id AND pitching.player_id = ?
            ORDER BY game.schedule_order
            """,
            (scope_value, player_id, player_id),
        ).fetchall()
        return {
            "scope_type": "opponent" if opponent is not None else "group",
            "scope_value": scope_value,
            "aggregate": dict(aggregate),
            "games": [dict(row) for row in games],
        }
    finally:
        connection.close()


def query_player_boxed_totals(
    database_path: Path, player_id: str
) -> dict[str, object]:
    """Return whole-season sums from every available game box score."""
    connection = _read_connection(database_path)
    try:
        _require_value(
            connection,
            table="players",
            column="player_id",
            value=player_id,
            label="player ID",
        )
        batting = connection.execute(
            """
            SELECT COALESCE(SUM(ab), 0) AS at_bats,
                   COALESCE(SUM(r), 0) AS runs,
                   COALESCE(SUM(h), 0) AS hits,
                   COALESCE(SUM(rbi), 0) AS runs_batted_in,
                   COALESCE(SUM(bb), 0) AS walks,
                   COALESCE(SUM(so), 0) AS strikeouts
            FROM game_batting WHERE player_id = ?
            """,
            (player_id,),
        ).fetchone()
        pitching = connection.execute(
            """
            SELECT COALESCE(SUM(outs), 0) AS outs,
                   COALESCE(SUM(h), 0) AS hits,
                   COALESCE(SUM(r), 0) AS runs,
                   COALESCE(SUM(er), 0) AS earned_runs,
                   COALESCE(SUM(bb), 0) AS walks,
                   COALESCE(SUM(so), 0) AS strikeouts,
                   COALESCE(SUM(decision LIKE 'W,%'), 0) AS wins,
                   COALESCE(SUM(decision LIKE 'L,%'), 0) AS losses,
                   COALESCE(SUM(decision LIKE 'S,%'), 0) AS saves
            FROM game_pitching WHERE player_id = ?
            """,
            (player_id,),
        ).fetchone()
        return {"batting": dict(batting), "pitching": dict(pitching)}
    finally:
        connection.close()


def query_hitter_series_candidates(
    database_path: Path, player_id: str
) -> dict[str, object]:
    """Return exact series H/AB candidates plus season residual inputs."""
    connection = _read_connection(database_path)
    try:
        _require_value(
            connection,
            table="players",
            column="player_id",
            value=player_id,
            label="player ID",
        )
        season = connection.execute(
            """
            SELECT line.at_bats, line.hits, line.source_id, line.source_locator,
                   source.original_url, source.raw_path
            FROM season_batting AS line
            JOIN sources AS source ON source.source_id = line.source_id
            WHERE line.scope = 'overall' AND line.player_id = ?
            """,
            (player_id,),
        ).fetchone()
        boxed = connection.execute(
            """
            SELECT COALESCE(SUM(ab), 0) AS at_bats, COALESCE(SUM(h), 0) AS hits
            FROM game_batting WHERE player_id = ?
            """,
            (player_id,),
        ).fetchone()
        series = connection.execute(
            """
            SELECT groups.group_id, groups.label, groups.start_date, groups.end_date,
                   groups.source_id, groups.source_locator,
                   source.original_url, source.raw_path,
                   COUNT(members.game_id) AS member_games,
                   SUM(EXISTS (
                       SELECT 1 FROM game_sources AS source_link
                       WHERE source_link.game_id = members.game_id
                         AND source_link.relationship = 'box_score'
                   )) AS box_games,
                   SUM(COALESCE(line.ab, 0)) AS at_bats,
                   SUM(COALESCE(line.h, 0)) AS hits
            FROM schedule_groups AS groups
            JOIN schedule_group_games AS members USING (group_id)
            JOIN sources AS source ON source.source_id = groups.source_id
            LEFT JOIN game_batting AS line
              ON line.game_id = members.game_id AND line.player_id = ?
            WHERE groups.group_type = 'series'
            GROUP BY groups.group_id
            ORDER BY groups.start_date, groups.group_id
            """,
            (player_id,),
        ).fetchall()
        return {
            "season": dict(season) if season else None,
            "boxed": dict(boxed),
            "series": [dict(row) for row in series],
        }
    finally:
        connection.close()


def query_team_leader_rows(
    database_path: Path,
    *,
    discipline: str,
    metric: str,
    scope: str = "overall",
) -> list[dict[str, object]]:
    """Return player season rows for one code-whitelisted leader metric."""
    if scope not in {"overall", "conference"}:
        raise QueryError(f"unsupported season scope: {scope}")
    if discipline == "batting":
        table = "season_batting"
        allowed = BATTING_LEADER_COLUMNS
        sample_columns = "line.at_bats, NULL AS outs"
    elif discipline == "pitching":
        table = "season_pitching"
        allowed = PITCHING_LEADER_COLUMNS
        sample_columns = "NULL AS at_bats, line.outs"
    else:
        raise QueryError(f"unsupported leader discipline: {discipline}")
    if metric not in allowed:
        raise QueryError(f"unsupported {discipline} leader metric: {metric}")
    connection = _read_connection(database_path)
    try:
        rows = connection.execute(
            f"""
            SELECT player.player_id, player.full_name, line.{metric} AS value,
                   {sample_columns}, line.source_id, line.source_locator,
                   source.original_url, source.raw_path
            FROM {table} AS line
            JOIN players AS player ON player.player_id = line.player_id
            JOIN sources AS source ON source.source_id = line.source_id
            WHERE line.scope = ? AND line.subject_type = 'player'
              AND line.{metric} IS NOT NULL
            ORDER BY player.full_name
            """,
            (scope,),
        ).fetchall()
        return [dict(row) for row in rows]
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
