"""Parsers for the preserved 2017 SDSU corpus sources."""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
import re
from typing import Iterable

from .corpus_inventory import canonical_opponent, decode_html
from .parse import ParseError


BATTING_COLUMNS = ("ab", "r", "h", "rbi", "bb", "so", "po", "a", "lob")
PITCHING_COLUMNS = (
    "ip",
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
SUPPLEMENTAL_FIELDS = {
    "E": "errors",
    "2B": "doubles",
    "3B": "triples",
    "HR": "home_runs",
    "HBP": "hit_by_pitch",
    "SH": "sacrifice_hits",
    "SF": "sacrifice_flies",
    "SB": "stolen_bases",
    "CS": "caught_stealing",
}
SEASON_BATTING_COLUMNS = (
    "avg",
    "gp-gs",
    "ab",
    "r",
    "h",
    "2b",
    "3b",
    "hr",
    "rbi",
    "tb",
    "slg%",
    "bb",
    "hbp",
    "so",
    "gdp",
    "ob%",
    "sf",
    "sh",
    "sb-att",
    "po",
    "a",
    "e",
    "fld%",
)
SEASON_PITCHING_COLUMNS = (
    "era",
    "w-l",
    "app-gs",
    "cg",
    "sho",
    "sv",
    "ip",
    "h",
    "r",
    "er",
    "bb",
    "so",
    "2b",
    "3b",
    "hr",
    "ab",
    "b/avg",
    "wp",
    "hbp",
    "bk",
    "sfa",
    "sha",
)
SEASON_FIELDING_COLUMNS = (
    "c",
    "po",
    "a",
    "e",
    "fld%",
    "dp",
    "sba",
    "csb",
    "sba%",
    "pb",
    "ci",
)


def _clean(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def _integer(value: str, context: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise ParseError(f"non-integer {value!r} in {context}") from exc


def innings_to_outs(value: str) -> int:
    whole, separator, fraction = value.partition(".")
    if not separator:
        fraction = "0"
    if fraction not in {"0", "1", "2"}:
        raise ParseError(f"invalid innings-pitched value: {value}")
    try:
        return int(whole) * 3 + int(fraction)
    except ValueError as exc:
        raise ParseError(f"invalid innings-pitched value: {value}") from exc


def _split_pair(value: str, context: str) -> tuple[int, int]:
    left, separator, right = value.partition("-")
    if not separator:
        raise ParseError(f"invalid paired value {value!r} in {context}")
    return _integer(left, context), _integer(right, context)


def _split_slash_pair(value: str, context: str) -> tuple[int, int]:
    left, separator, right = value.partition("/")
    if not separator:
        raise ParseError(f"invalid slash-paired value {value!r} in {context}")
    return _integer(left, context), _integer(right, context)


def _percentage(value: str) -> str | None:
    return None if value == "---" else value


def _person_name(value: str, *, has_position: bool) -> tuple[str, str | None]:
    cleaned = re.sub(r"^[a-z]-", "", _clean(value), flags=re.IGNORECASE)
    position: str | None = None
    if has_position:
        try:
            cleaned, position = cleaned.rsplit(" ", 1)
        except ValueError as exc:
            raise ParseError(f"cannot split player and position: {value!r}") from exc
    if "," not in cleaned:
        raise ParseError(f"cannot parse player name: {value!r}")
    last, first = (_clean(part) for part in cleaned.split(",", 1))
    if not first or not last:
        raise ParseError(f"cannot parse player name: {value!r}")

    def display_token(token: str) -> str:
        if token.upper().rstrip(".") in {"CJ", "AJ", "DJ", "TJ"}:
            return token.upper().rstrip(".")
        if token.isupper():
            return token.title()
        return token

    first_display = " ".join(display_token(token) for token in first.split())
    last_display = " ".join(display_token(token) for token in last.split())
    return f"{first_display} {last_display}", position


def person_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _team_key(value: str) -> str:
    cleaned = re.sub(r"^#\d+(?:/\d+)?\s+", "", _clean(value))
    cleaned = re.sub(r"\s+\(Game\s*\d+\)$", "", cleaned, flags=re.IGNORECASE)
    return re.sub(r"[^a-z0-9]+", "", cleaned.casefold())


def _team_role(value: str, opponent: str) -> str | None:
    key = _team_key(value)
    if key in {"sandiegostate", "sandiegost", "sdsu", "aztecs"}:
        return "sdsu"
    opponent_key = _team_key(canonical_opponent(opponent))
    if key == opponent_key:
        return "opponent"
    return None


@dataclass(frozen=True)
class RosterPlayer:
    player_id: str
    jersey_number: str
    full_name: str
    position: str
    height: str
    weight: str
    class_year: str
    hometown: str
    high_school: str
    previous_school: str | None
    source_locator: str


@dataclass(frozen=True)
class StaffMember:
    staff_id: str
    full_name: str
    title: str
    source_locator: str


@dataclass(frozen=True)
class SeasonStatRow:
    scope: str
    subject_type: str
    subject_name: str
    values: dict[str, object]
    source_locator: str


@dataclass(frozen=True)
class SeasonRecord:
    label: str
    wins: int
    losses: int
    source_locator: str


@dataclass(frozen=True)
class SeasonStatNote:
    scope: str
    note_order: int
    text: str
    source_locator: str


@dataclass(frozen=True)
class ParsedSeasonStatistics:
    batting: tuple[SeasonStatRow, ...]
    pitching: tuple[SeasonStatRow, ...]
    fielding: tuple[SeasonStatRow, ...]
    records: tuple[SeasonRecord, ...]
    notes: tuple[SeasonStatNote, ...]
    inning_runs: tuple[tuple[str, str, int, str], ...]


@dataclass(frozen=True)
class GameBattingLine:
    player_name: str
    position: str
    values: dict[str, int | None]
    source_locator: str


@dataclass(frozen=True)
class GamePitchingLine:
    player_name: str
    decision: str | None
    values: dict[str, int | None]
    source_locator: str


@dataclass(frozen=True)
class PlayByPlayPassage:
    sequence: int
    inning: int
    batting_team: str
    text: str
    source_locator: str


@dataclass(frozen=True)
class ParsedBoxScore:
    game_id: str
    sdsu_score: int
    opponent_score: int
    batting_lines: tuple[GameBattingLine, ...]
    pitching_lines: tuple[GamePitchingLine, ...]
    batting_totals: dict[str, int]
    play_by_play: tuple[PlayByPlayPassage, ...]
    source_locator: str


@dataclass(frozen=True)
class ArticlePassage:
    passage_order: int
    text: str
    source_locator: str
    block_type: str


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[dict[str, object]] = []
        self.tables: list[list[list[str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self.stack.append({"rows": [], "row": None, "cell": None})
        elif not self.stack:
            return
        elif tag == "tr":
            self.stack[-1]["row"] = []
        elif tag in {"td", "th"} and self.stack[-1]["row"] is not None:
            self.stack[-1]["cell"] = []

    def handle_data(self, data: str) -> None:
        if self.stack and self.stack[-1]["cell"] is not None:
            cell = self.stack[-1]["cell"]
            assert isinstance(cell, list)
            cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self.stack:
            return
        current = self.stack[-1]
        if tag in {"td", "th"} and current["cell"] is not None:
            row = current["row"]
            cell = current["cell"]
            assert isinstance(row, list) and isinstance(cell, list)
            row.append(_clean("".join(cell)))
            current["cell"] = None
        elif tag == "tr" and current["row"] is not None:
            rows = current["rows"]
            row = current["row"]
            assert isinstance(rows, list) and isinstance(row, list)
            if any(row):
                rows.append(row)
            current["row"] = None
            current["cell"] = None
        elif tag == "table":
            completed = self.stack.pop()
            rows = completed["rows"]
            assert isinstance(rows, list)
            if rows:
                self.tables.append(rows)


def _tables(content: bytes) -> list[list[list[str]]]:
    parser = _TableParser()
    parser.feed(decode_html(content))
    parser.close()
    return parser.tables


def parse_roster(content: bytes) -> tuple[tuple[RosterPlayer, ...], tuple[StaffMember, ...]]:
    tables = _tables(content)
    player_table = next(
        (
            table
            for table in tables
            if table
            and tuple(cell.casefold() for cell in table[0][:3])
            == ("# jersey number", "name", "position")
        ),
        None,
    )
    staff_table = next(
        (
            table
            for table in tables
            if table and tuple(cell.casefold() for cell in table[0]) == ("name", "title")
        ),
        None,
    )
    if player_table is None or staff_table is None:
        raise ParseError("roster player or staff table is missing")
    players: list[RosterPlayer] = []
    for row_number, row in enumerate(player_table[1:], start=2):
        if len(row) != 10:
            raise ParseError(f"unexpected roster row shape at row {row_number}: {row}")
        full_name = row[1]
        players.append(
            RosterPlayer(
                player_id=re.sub(r"[^a-z0-9]+", "-", full_name.casefold()).strip("-"),
                jersey_number=row[0],
                full_name=full_name,
                position=row[2],
                height=row[3],
                weight=row[4],
                class_year=row[5],
                hometown=row[6],
                high_school=row[7],
                previous_school=row[8] or None,
                source_locator=f"roster/player-table/row[{row_number}]",
            )
        )
    staff: list[StaffMember] = []
    for row_number, row in enumerate(staff_table[1:], start=2):
        if len(row) != 2:
            raise ParseError(f"unexpected staff row shape at row {row_number}: {row}")
        staff.append(
            StaffMember(
                staff_id=re.sub(r"[^a-z0-9]+", "-", row[0].casefold()).strip("-"),
                full_name=row[0],
                title=row[1],
                source_locator=f"roster/staff-table/row[{row_number}]",
            )
        )
    return tuple(players), tuple(staff)


def _season_subject(name: str) -> tuple[str, str]:
    if name.casefold() == "totals":
        return "team", "San Diego State"
    if name.casefold() == "opponents":
        return "opponents", "Opponents"
    full_name, _ = _person_name(name, has_position=False)
    return "player", full_name


def _season_batting_values(row: list[str], context: str) -> dict[str, object]:
    raw = dict(zip(SEASON_BATTING_COLUMNS, row, strict=True))
    games, starts = _split_pair(str(raw["gp-gs"]), context)
    stolen_bases, stolen_base_attempts = _split_pair(str(raw["sb-att"]), context)
    return {
        "batting_average": _percentage(str(raw["avg"])),
        "games": games,
        "starts": starts,
        **{
            key: _integer(str(raw[source]), context)
            for key, source in {
                "at_bats": "ab",
                "runs": "r",
                "hits": "h",
                "doubles": "2b",
                "triples": "3b",
                "home_runs": "hr",
                "runs_batted_in": "rbi",
                "total_bases": "tb",
                "walks": "bb",
                "hit_by_pitch": "hbp",
                "strikeouts": "so",
                "grounded_into_double_plays": "gdp",
                "sacrifice_flies": "sf",
                "sacrifice_hits": "sh",
                "putouts": "po",
                "assists": "a",
                "errors": "e",
            }.items()
        },
        "slugging_percentage": _percentage(str(raw["slg%"])),
        "on_base_percentage": _percentage(str(raw["ob%"])),
        "stolen_bases": stolen_bases,
        "stolen_base_attempts": stolen_base_attempts,
        "fielding_percentage": _percentage(str(raw["fld%"])),
    }


def _season_pitching_values(row: list[str], context: str) -> dict[str, object]:
    raw = dict(zip(SEASON_PITCHING_COLUMNS, row, strict=True))
    wins, losses = _split_pair(str(raw["w-l"]), context)
    appearances, starts = _split_pair(str(raw["app-gs"]), context)
    shutouts, combined_shutouts = _split_slash_pair(str(raw["sho"]), context)
    return {
        "earned_run_average": _percentage(str(raw["era"])),
        "wins": wins,
        "losses": losses,
        "appearances": appearances,
        "starts": starts,
        "complete_games": _integer(str(raw["cg"]), context),
        "shutouts": shutouts,
        "combined_shutouts": combined_shutouts,
        "saves": _integer(str(raw["sv"]), context),
        "outs": innings_to_outs(str(raw["ip"])),
        **{
            key: _integer(str(raw[source]), context)
            for key, source in {
                "hits": "h",
                "runs": "r",
                "earned_runs": "er",
                "walks": "bb",
                "strikeouts": "so",
                "doubles_allowed": "2b",
                "triples_allowed": "3b",
                "home_runs_allowed": "hr",
                "at_bats_against": "ab",
                "wild_pitches": "wp",
                "hit_batters": "hbp",
                "balks": "bk",
                "sacrifice_flies_allowed": "sfa",
                "sacrifice_hits_allowed": "sha",
            }.items()
        },
        "opponent_batting_average": _percentage(str(raw["b/avg"])),
    }


def _season_fielding_values(row: list[str], context: str) -> dict[str, object]:
    raw = dict(zip(SEASON_FIELDING_COLUMNS, row, strict=True))
    return {
        "chances": _integer(str(raw["c"]), context),
        "putouts": _integer(str(raw["po"]), context),
        "assists": _integer(str(raw["a"]), context),
        "errors": _integer(str(raw["e"]), context),
        "fielding_percentage": _percentage(str(raw["fld%"])),
        "double_plays": _integer(str(raw["dp"]), context),
        "stolen_bases_allowed": _integer(str(raw["sba"]), context),
        "caught_stealing": _integer(str(raw["csb"]), context),
        "stolen_base_percentage": _percentage(str(raw["sba%"])),
        "passed_balls": _integer(str(raw["pb"]), context),
        "catcher_interference": _integer(str(raw["ci"]), context),
    }


def parse_season_statistics(content: bytes) -> ParsedSeasonStatistics:
    tables = _tables(content)
    batting_tables = [
        (index, table)
        for index, table in enumerate(tables, start=1)
        if table
        and tuple(cell.casefold() for cell in table[0][1:]) == SEASON_BATTING_COLUMNS
    ]
    pitching_tables = [
        (index, table)
        for index, table in enumerate(tables, start=1)
        if table
        and tuple(cell.casefold() for cell in table[0][1:]) == SEASON_PITCHING_COLUMNS
    ]
    fielding_tables = [
        (index, table)
        for index, table in enumerate(tables, start=1)
        if table
        and tuple(cell.casefold() for cell in table[0][1:]) == SEASON_FIELDING_COLUMNS
    ]
    if not (
        len(batting_tables) == len(pitching_tables) == len(fielding_tables) == 2
    ):
        raise ParseError("expected overall and conference season-statistics tables")

    batting: list[SeasonStatRow] = []
    pitching: list[SeasonStatRow] = []
    fielding: list[SeasonStatRow] = []
    for scope_index, scope in enumerate(("overall", "conference")):
        table_number, table = batting_tables[scope_index]
        for row_number, row in enumerate(table[1:], start=2):
            if len(row) != 24:
                raise ParseError(f"unexpected season batting row: {row}")
            subject_type, subject_name = _season_subject(row[0])
            context = f"{scope} batting for {subject_name}"
            batting.append(
                SeasonStatRow(
                    scope,
                    subject_type,
                    subject_name,
                    _season_batting_values(row[1:], context),
                    f"statistics/table[{table_number}]/row[{row_number}]",
                )
            )

        table_number, table = pitching_tables[scope_index]
        for row_number, row in enumerate(table[1:], start=2):
            if len(row) != 23:
                raise ParseError(f"unexpected season pitching row: {row}")
            subject_type, subject_name = _season_subject(row[0])
            context = f"{scope} pitching for {subject_name}"
            pitching.append(
                SeasonStatRow(
                    scope,
                    subject_type,
                    subject_name,
                    _season_pitching_values(row[1:], context),
                    f"statistics/table[{table_number}]/row[{row_number}]",
                )
            )

        table_number, table = fielding_tables[scope_index]
        for row_number, row in enumerate(table[1:], start=2):
            if len(row) != 12:
                raise ParseError(f"unexpected season fielding row: {row}")
            subject_type, subject_name = _season_subject(row[0])
            context = f"{scope} fielding for {subject_name}"
            fielding.append(
                SeasonStatRow(
                    scope,
                    subject_type,
                    subject_name,
                    _season_fielding_values(row[1:], context),
                    f"statistics/table[{table_number}]/row[{row_number}]",
                )
            )

    record_table_number, record_table = next(
        (
            (index, table)
            for index, table in enumerate(tables, start=1)
            if table and table[0] == ["Overall", "42-21"]
        ),
        (0, []),
    )
    if not record_table:
        raise ParseError("season record table is missing")
    records: list[SeasonRecord] = []
    for row_number, row in enumerate(record_table, start=1):
        if len(row) != 2 or not re.fullmatch(r"\d+-\d+", row[1]):
            continue
        wins, losses = _split_pair(row[1], f"season record {row[0]}")
        records.append(
            SeasonRecord(
                row[0],
                wins,
                losses,
                f"statistics/table[{record_table_number}]/row[{row_number}]",
            )
        )

    inning_table_number, inning_table = next(
        (
            (index, table)
            for index, table in enumerate(tables, start=1)
            if table and table[0] and table[0][0] == "Inning-by-inning"
        ),
        (0, []),
    )
    if not inning_table:
        raise ParseError("inning-by-inning season table is missing")
    inning_runs: list[tuple[str, str, int, str]] = []
    inning_labels = inning_table[0][1:]
    for row_number, row in enumerate(inning_table[1:], start=2):
        for label, value in zip(inning_labels, row[1:], strict=True):
            inning_runs.append(
                (
                    row[0],
                    label,
                    _integer(value, f"inning runs for {row[0]}"),
                    f"statistics/table[{inning_table_number}]/row[{row_number}]",
                )
            )

    note_tables = [
        (index, table[0][0])
        for index, table in enumerate(tables, start=1)
        if len(table) == 1
        and len(table[0]) == 1
        and table[0][0].startswith(("LOB -", "PB -"))
    ]
    notes = tuple(
        SeasonStatNote(
            scope="overall" if order <= 2 else "conference",
            note_order=((order - 1) % 2) + 1,
            text=text,
            source_locator=f"statistics/table[{table_number}]/row[1]",
        )
        for order, (table_number, text) in enumerate(note_tables, start=1)
    )
    if len(notes) != 4:
        raise ParseError(f"expected four season statistic notes, found {len(notes)}")
    return ParsedSeasonStatistics(
        tuple(batting),
        tuple(pitching),
        tuple(fielding),
        tuple(records),
        notes,
        tuple(inning_runs),
    )


@dataclass
class _LegacyTable:
    section: str
    rows: list[list[str]]


class _LegacyCorpusParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.section = "ROOT"
        self.table_depth = 0
        self.current_table: list[list[str]] | None = None
        self.current_row: list[str] | None = None
        self.current_cell: list[str] | None = None
        self.tables: list[_LegacyTable] = []
        self.text_segments: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "a" and attributes.get("name"):
            self._finish_table()
            self.section = str(attributes["name"]).upper()
            return
        if tag == "table":
            if self.table_depth == 0:
                self.current_table = []
            self.table_depth += 1
        elif tag == "tr" and self.table_depth == 1:
            self._finish_row()
            self.current_row = []
        elif tag in {"td", "th"} and self.table_depth == 1:
            self._finish_cell()
            if self.current_row is None:
                self.current_row = []
            self.current_cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self.table_depth == 1:
            self._finish_cell()
        elif tag == "tr" and self.table_depth == 1:
            self._finish_row()
        elif tag == "table" and self.table_depth:
            self.table_depth -= 1
            if self.table_depth == 0:
                self._finish_table()

    def handle_data(self, data: str) -> None:
        cleaned = _clean(data)
        if cleaned:
            self.text_segments.append((self.section, cleaned))
        if self.current_cell is not None:
            self.current_cell.append(data)

    def close(self) -> None:
        super().close()
        self._finish_table()

    def _finish_cell(self) -> None:
        if self.current_cell is None:
            return
        assert self.current_row is not None
        self.current_row.append(_clean("".join(self.current_cell)))
        self.current_cell = None

    def _finish_row(self) -> None:
        self._finish_cell()
        if self.current_row is not None and self.current_table is not None:
            if any(self.current_row):
                self.current_table.append(self.current_row)
        self.current_row = None

    def _finish_table(self) -> None:
        self._finish_row()
        if self.current_table:
            self.tables.append(_LegacyTable(self.section, self.current_table))
        self.current_table = None
        self.table_depth = 0


def _team_score(value: str) -> tuple[str, int] | None:
    match = re.fullmatch(r"(.+?)\s+(\d+)\s+\([^)]*\)", _clean(value))
    if not match:
        return None
    return match.group(1), int(match.group(2))


def _supplemental_values(
    lines: list[GameBattingLine], text_segments: Iterable[tuple[str, str]]
) -> None:
    summaries = [
        text
        for section, text in text_segments
        if section == "GAME.NCA"
        and re.search(r"(?:^|\.\s)(?:E|DP|LOB|2B|3B|HR|HBP|SH|SF|SB|CS)\s+-", text)
    ]
    if not summaries:
        return
    summary = max(summaries, key=len)
    labels = "|".join(("E", "DP", "LOB", "2B", "3B", "HR", "HBP", "SH", "SF", "SB", "CS"))
    sections = list(
        re.finditer(
            rf"(?:^|\.\s)(?P<label>{labels})\s+-\s+(?P<body>.*?)(?=(?:\.\s(?:{labels})\s+-)|$)",
            summary,
        )
    )
    by_last_name: dict[str, list[GameBattingLine]] = {}
    for line in lines:
        by_last_name.setdefault(line.player_name.rsplit(" ", 1)[-1].casefold(), []).append(line)
    for section in sections:
        field_name = SUPPLEMENTAL_FIELDS.get(section.group("label"))
        if field_name is None:
            continue
        for line in lines:
            line.values[field_name] = 0
        for raw_item in section.group("body").split(";"):
            item = raw_item.strip().rstrip(".")
            if not item:
                continue
            count_match = re.search(r"\s+(\d+)\(\d+\)$", item)
            count = int(count_match.group(1)) if count_match else 1
            name_part = re.sub(r"(?:\s+\d+)?\(\d+\)$", "", item).strip().rstrip(".")
            last_name = name_part.split(",", 1)[0].split()[0].casefold()
            candidates = by_last_name.get(last_name, [])
            if len(candidates) == 1:
                candidates[0].values[field_name] = count


def _parse_play_by_play(
    parser: _LegacyCorpusParser, opponent: str
) -> tuple[PlayByPlayPassage, ...]:
    passages: list[PlayByPlayPassage] = []
    for table_number, table in enumerate(parser.tables, start=1):
        if table.section != "GAME.PLY":
            continue
        for row_number, row in enumerate(table.rows, start=1):
            text = _clean(" ".join(row))
            match = re.match(r"^(.+?)\s+(\d+)(?:st|nd|rd|th)\s+-\s+(.+)$", text)
            if not match:
                continue
            team = match.group(1)
            role = _team_role(team, opponent)
            batting_team = (
                "San Diego State"
                if role == "sdsu"
                else canonical_opponent(opponent) if role == "opponent" else team
            )
            passages.append(
                PlayByPlayPassage(
                    sequence=len(passages) + 1,
                    inning=int(match.group(2)),
                    batting_team=batting_team,
                    text=match.group(3),
                    source_locator=f"GAME.PLY/table[{table_number}]/row[{row_number}]",
                )
            )
    return tuple(passages)


def parse_corpus_box_score(
    content: bytes,
    *,
    game_id: str,
    opponent: str,
) -> ParsedBoxScore:
    parser = _LegacyCorpusParser()
    parser.feed(decode_html(content))
    parser.close()
    nca_tables = [table for table in parser.tables if table.section == "GAME.NCA"]
    if not nca_tables:
        raise ParseError(f"{game_id}: GAME.NCA box-score section is missing")

    scores: dict[str, int] = {}
    batting_lines: list[GameBattingLine] = []
    batting_totals: dict[str, int] = {}
    current_role: str | None = None
    batting_mode = False
    for table_number, table in enumerate(nca_tables, start=1):
        for row_number, row in enumerate(table.rows, start=1):
            if len(row) == 1:
                score = _team_score(row[0])
                if score:
                    current_role = _team_role(score[0], opponent)
                    if current_role:
                        scores[current_role] = score[1]
                    batting_mode = False
                continue
            lowered = tuple(cell.casefold() for cell in row)
            if lowered == ("player", *BATTING_COLUMNS):
                batting_mode = True
                continue
            if len(row) >= 15 and tuple(cell.casefold() for cell in row[1:7]) == (
                "ip",
                "h",
                "r",
                "er",
                "bb",
                "so",
            ):
                batting_mode = False
                continue
            if current_role != "sdsu" or not batting_mode or len(row) != 10:
                continue
            if row[0].casefold() == "totals":
                batting_totals = {
                    key: _integer(value, f"{game_id} SDSU batting totals")
                    for key, value in zip(BATTING_COLUMNS, row[1:], strict=True)
                }
                batting_mode = False
                continue
            player_name, position = _person_name(row[0], has_position=True)
            values: dict[str, int | None] = {
                key: _integer(value, f"{game_id} batting line for {player_name}")
                for key, value in zip(BATTING_COLUMNS, row[1:], strict=True)
            }
            values.update({field: None for field in SUPPLEMENTAL_FIELDS.values()})
            batting_lines.append(
                GameBattingLine(
                    player_name,
                    position or "",
                    values,
                    f"GAME.NCA/table[{table_number}]/row[{row_number}]",
                )
            )
    _supplemental_values(batting_lines, parser.text_segments)

    pitching_lines: list[GamePitchingLine] = []
    current_pitch_role: str | None = None
    pitch_headers: tuple[str, ...] = ()
    for table_number, table in enumerate(nca_tables, start=1):
        for row_number, row in enumerate(table.rows, start=1):
            lowered = tuple(cell.casefold() for cell in row)
            if len(row) >= 15 and lowered[1:7] == ("ip", "h", "r", "er", "bb", "so"):
                current_pitch_role = _team_role(row[0], opponent)
                pitch_headers = lowered[1:]
                continue
            if current_pitch_role != "sdsu" or not pitch_headers:
                continue
            if len(row) != len(pitch_headers) + 1 or not row[0]:
                continue
            decision_match = re.search(r"\s+((?:W|L|S),\d+(?:-\d+)?)$", row[0])
            decision = decision_match.group(1) if decision_match else None
            name_cell = row[0][: decision_match.start()] if decision_match else row[0]
            player_name, _ = _person_name(name_cell, has_position=False)
            values: dict[str, int | None] = {
                column: None for column in PITCHING_COLUMNS if column != "ip"
            }
            values["outs"] = innings_to_outs(row[1])
            for column, value in zip(pitch_headers[1:], row[2:], strict=True):
                values[column] = _integer(value, f"{game_id} pitching line for {player_name}")
            pitching_lines.append(
                GamePitchingLine(
                    player_name,
                    decision,
                    values,
                    f"GAME.NCA/table[{table_number}]/row[{row_number}]",
                )
            )

    missing_scores = {"sdsu", "opponent"} - scores.keys()
    if missing_scores:
        raise ParseError(f"{game_id}: box score is missing {sorted(missing_scores)} score")
    if not batting_lines or not batting_totals or not pitching_lines:
        raise ParseError(
            f"{game_id}: incomplete box score: batting={len(batting_lines)}, "
            f"pitching={len(pitching_lines)}, totals={bool(batting_totals)}"
        )
    return ParsedBoxScore(
        game_id=game_id,
        sdsu_score=scores["sdsu"],
        opponent_score=scores["opponent"],
        batting_lines=tuple(batting_lines),
        pitching_lines=tuple(pitching_lines),
        batting_totals=batting_totals,
        play_by_play=_parse_play_by_play(parser, opponent),
        source_locator="GAME.NCA/team score headings",
    )


class _ArticleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.embed_depth = 0
        self.current: list[str] | None = None
        self.current_tag: str | None = None
        self.anchor_depth = 0
        self.has_text_outside_anchor = False
        self.paragraphs: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = set((dict(attrs).get("class") or "").split())
        if tag == "div" and "embed-html" in classes and self.embed_depth == 0:
            self.embed_depth = 1
            return
        if not self.embed_depth:
            return
        if tag == "div":
            self.embed_depth += 1
        elif tag in {"p", "li", "h2", "h3"} and self.current is None:
            self.current = []
            self.current_tag = tag
            self.anchor_depth = 0
            self.has_text_outside_anchor = False
        elif tag == "a" and self.current is not None:
            self.anchor_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if not self.embed_depth:
            return
        if tag in {"p", "li", "h2", "h3"}:
            self._finish()
        elif tag == "a" and self.current is not None:
            self.anchor_depth = max(0, self.anchor_depth - 1)
        elif tag == "div":
            self.embed_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.current is not None:
            self.current.append(data)
            if self.anchor_depth == 0 and data.strip():
                self.has_text_outside_anchor = True

    def close(self) -> None:
        super().close()
        self._finish()

    def _finish(self) -> None:
        if self.current is None:
            return
        text = _clean("".join(self.current))
        if self.current_tag in {"h2", "h3"}:
            block_type = "heading"
        elif not self.has_text_outside_anchor or re.fullmatch(
            r"[^.]{0,100}Box Score(?:\s*\|\s*[^.]{0,100}Box Score)*",
            text,
            flags=re.IGNORECASE,
        ):
            block_type = "resource_link"
        elif re.fullmatch(
            r"(?:Jan\.|January|Feb\.|February|Mar\.|March|Apr\.|April|May|"
            r"Jun\.|June|Jul\.|July|Aug\.|August|Sep\.|September|Oct\.|October|"
            r"Nov\.|November|Dec\.|December)"
            r"\s+\d{1,2},\s+\d{4}",
            text,
        ):
            block_type = "dateline"
        else:
            block_type = "narrative"
        if text and (not self.paragraphs or self.paragraphs[-1][0] != text):
            self.paragraphs.append((text, block_type))
        self.current = None
        self.current_tag = None
        self.anchor_depth = 0
        self.has_text_outside_anchor = False


def parse_article(content: bytes) -> tuple[ArticlePassage, ...]:
    parser = _ArticleParser()
    parser.feed(decode_html(content))
    parser.close()
    return tuple(
        ArticlePassage(
            passage_order=order,
            text=text,
            source_locator=f"embed-html/block[{order}]",
            block_type=block_type,
        )
        for order, (text, block_type) in enumerate(parser.paragraphs, start=1)
    )
