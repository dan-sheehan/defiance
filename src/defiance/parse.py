"""Source-specific parsing for the February 17, 2017 Pacific game."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import gzip
from html.parser import HTMLParser
import re
from typing import Iterable


class ParseError(ValueError):
    """Raised when reviewed source structure is absent or inconsistent."""


BATTING_COLUMNS = ("player", "ab", "r", "h", "rbi", "bb", "so", "po", "a", "lob")
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


def _clean(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def _decode_html(content: bytes, source_name: str) -> str:
    try:
        decoded = gzip.decompress(content) if content.startswith(b"\x1f\x8b") else content
        return decoded.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ParseError(f"{source_name} is not readable UTF-8 HTML") from exc


@dataclass
class BattingLine:
    player_name: str
    position: str
    ab: int
    r: int
    h: int
    rbi: int
    bb: int
    so: int
    po: int
    a: int
    lob: int
    doubles: int = 0
    triples: int = 0
    home_runs: int = 0
    hit_by_pitch: int = 0
    sacrifice_hits: int = 0
    sacrifice_flies: int = 0
    stolen_bases: int = 0
    caught_stealing: int = 0
    errors: int = 0
    source_locator: str = ""


@dataclass(frozen=True)
class PitchingLine:
    player_name: str
    decision: str | None
    outs: int
    h: int
    r: int
    er: int
    bb: int
    so: int
    wp: int
    bk: int
    hbp: int
    ibb: int
    ab: int
    bf: int
    fo: int
    go: int
    np: int
    source_locator: str


@dataclass(frozen=True)
class ParsedGame:
    game_id: str
    game_date: date
    opponent: str
    sdsu_score: int
    opponent_score: int
    batting_lines: tuple[BattingLine, ...]
    pitching_lines: tuple[PitchingLine, ...]
    batting_totals: dict[str, int]
    source_locator: str


@dataclass(frozen=True)
class RecapPassage:
    passage_order: int
    text: str
    source_locator: str


class _LegacyReportParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_nca = False
        self.table_depth = 0
        self.current_table: list[list[str]] | None = None
        self.current_row: list[str] | None = None
        self.current_cell: list[str] | None = None
        self.tables: list[list[list[str]]] = []
        self.text_segments: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "a" and attributes.get("name") == "GAME.NCA":
            self.in_nca = True
            return
        if tag == "a" and attributes.get("name") == "GAME.PLY":
            self._finish_table()
            self.in_nca = False
            return
        if not self.in_nca:
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
        if not self.in_nca:
            return
        if tag in {"td", "th"} and self.table_depth == 1:
            self._finish_cell()
        elif tag == "tr" and self.table_depth == 1:
            self._finish_row()
        elif tag == "table" and self.table_depth:
            self.table_depth -= 1
            if self.table_depth == 0:
                self._finish_table()

    def handle_data(self, data: str) -> None:
        if not self.in_nca:
            return
        cleaned = _clean(data)
        if cleaned:
            self.text_segments.append(cleaned)
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
            self.tables.append(self.current_table)
        self.current_table = None
        self.table_depth = 0


class _RecapHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.embed_depth = 0
        self.current_paragraph: list[str] | None = None
        self.paragraphs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        if tag == "div" and "embed-html" in classes and self.embed_depth == 0:
            self.embed_depth = 1
            return
        if self.embed_depth and tag == "div":
            self.embed_depth += 1
        elif self.embed_depth and tag == "p":
            self._finish_paragraph()
            self.current_paragraph = []

    def handle_endtag(self, tag: str) -> None:
        if not self.embed_depth:
            return
        if tag == "p":
            self._finish_paragraph()
        elif tag == "div":
            self.embed_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.embed_depth and self.current_paragraph is not None:
            self.current_paragraph.append(data)

    def close(self) -> None:
        super().close()
        self._finish_paragraph()

    def _finish_paragraph(self) -> None:
        if self.current_paragraph is None:
            return
        text = _clean("".join(self.current_paragraph))
        if text:
            self.paragraphs.append(text)
        self.current_paragraph = None


def _source_name(cell: str, *, has_position: bool) -> tuple[str, str | None]:
    value = _clean(cell)
    position: str | None = None
    if has_position:
        try:
            value, position = value.rsplit(" ", 1)
        except ValueError as exc:
            raise ParseError(f"cannot split player and position: {cell!r}") from exc
    if "," not in value:
        raise ParseError(f"cannot parse player name: {cell!r}")
    last, first = (_clean(part) for part in value.split(",", 1))
    if not first or not last:
        raise ParseError(f"cannot parse player name: {cell!r}")
    last_tokens = [token if token in {"II", "III", "IV"} else token.title() for token in last.split()]
    return f"{first} {' '.join(last_tokens)}", position


def _integers(values: Iterable[str], *, context: str) -> list[int]:
    try:
        return [int(value) for value in values]
    except ValueError as exc:
        raise ParseError(f"non-integer value in {context}") from exc


def _outs(value: str) -> int:
    whole, separator, fraction = value.partition(".")
    if not separator:
        fraction = "0"
    if fraction not in {"0", "1", "2"}:
        raise ParseError(f"invalid innings-pitched value: {value}")
    try:
        return int(whole) * 3 + int(fraction)
    except ValueError as exc:
        raise ParseError(f"invalid innings-pitched value: {value}") from exc


def _team_score(value: str) -> tuple[str, int] | None:
    match = re.fullmatch(r"(.+?)\s+(\d+)\s+\([^)]*\)", _clean(value))
    if not match:
        return None
    return match.group(1), int(match.group(2))


def _game_id(game_date: date, opponent: str) -> str:
    opponent_slug = re.sub(r"[^a-z0-9]+", "-", opponent.casefold()).strip("-")
    return f"{game_date.isoformat()}-{opponent_slug}"


def _add_supplemental(lines: list[BattingLine], text_segments: list[str]) -> None:
    supplemental = next((text for text in text_segments if text.startswith("E - ")), None)
    if supplemental is None:
        return

    by_last_name = {line.player_name.rsplit(" ", 1)[-1].upper(): line for line in lines}
    labels = "|".join(("E", "DP", "LOB", "2B", "3B", "HR", "HBP", "SH", "SF", "SB", "CS"))
    sections = re.finditer(
        rf"(?:^|\.\s)(?P<label>{labels})\s+-\s+(?P<body>.*?)(?=(?:\.\s(?:{labels})\s+-)|$)",
        supplemental,
    )
    for section in sections:
        field_name = SUPPLEMENTAL_FIELDS.get(section.group("label"))
        if field_name is None:
            continue
        for raw_item in section.group("body").split(";"):
            item = raw_item.strip().rstrip(".")
            if not item:
                continue
            count_match = re.search(r"\s+(\d+)\(\d+\)$", item)
            count = int(count_match.group(1)) if count_match else 1
            name_part = re.sub(r"(?:\s+\d+)?\(\d+\)$", "", item).strip().rstrip(".")
            last_name = name_part.split(",", 1)[0].split()[0].upper()
            line = by_last_name.get(last_name)
            if line is not None:
                setattr(line, field_name, count)


def parse_box_score(content: bytes) -> ParsedGame:
    parser = _LegacyReportParser()
    parser.feed(_decode_html(content, "box score"))
    parser.close()

    game_date: date | None = None
    matchup: str | None = None
    for segment in parser.text_segments:
        date_match = re.fullmatch(r"([A-Z][a-z]{2} \d{1,2}, \d{4}) at .+", segment)
        if date_match:
            game_date = datetime.strptime(date_match.group(1), "%b %d, %Y").date()
        if " at " in segment and not re.match(r"[A-Z][a-z]{2} \d", segment):
            left, right = segment.split(" at ", 1)
            if left == "San Diego State" or right == "San Diego State":
                matchup = segment
    if game_date is None or matchup is None:
        raise ParseError("required game metadata is missing from GAME.NCA")

    left_team, right_team = matchup.split(" at ", 1)
    if right_team == "San Diego State":
        opponent = left_team
    elif left_team == "San Diego State":
        opponent = right_team
    else:
        raise ParseError("GAME.NCA matchup does not include San Diego State")

    scores: dict[str, int] = {}
    batting_lines: list[BattingLine] = []
    pitching_lines: list[PitchingLine] = []
    batting_totals: dict[str, int] = {}
    current_team: str | None = None
    batting_mode = False

    batting_row_number = 0
    pitching_row_number = 0
    for table in parser.tables:
        for row in table:
            if len(row) == 1:
                parsed_score = _team_score(row[0])
                if parsed_score:
                    current_team, score = parsed_score
                    scores[current_team] = score
                    batting_mode = False
                continue

            lowered = tuple(cell.casefold() for cell in row)
            if lowered == BATTING_COLUMNS:
                batting_mode = True
                continue
            if len(row) == 16 and tuple(cell.casefold() for cell in row[1:]) == PITCHING_COLUMNS:
                current_team = row[0]
                batting_mode = False
                continue

            if current_team != "San Diego State":
                continue
            if batting_mode and len(row) == 10:
                if row[0].casefold() == "totals":
                    values = _integers(row[1:], context="SDSU batting totals")
                    batting_totals = dict(zip(BATTING_COLUMNS[1:], values, strict=True))
                    batting_mode = False
                    continue
                player_name, position = _source_name(row[0], has_position=True)
                values = _integers(row[1:], context=f"batting line for {player_name}")
                batting_row_number += 1
                batting_lines.append(
                    BattingLine(
                        player_name,
                        position or "",
                        *values,
                        source_locator=f"GAME.NCA/San Diego State batting/row[{batting_row_number}]",
                    )
                )
            elif not batting_mode and len(row) == 16 and row[0]:
                decision_match = re.search(r"\s+((?:W|L|S),\d+-\d+)$", row[0])
                decision = decision_match.group(1) if decision_match else None
                name_cell = row[0][: decision_match.start()] if decision_match else row[0]
                player_name, _ = _source_name(name_cell, has_position=False)
                values = _integers(row[2:], context=f"pitching line for {player_name}")
                pitching_row_number += 1
                pitching_lines.append(
                    PitchingLine(
                        player_name=player_name,
                        decision=decision,
                        outs=_outs(row[1]),
                        h=values[0],
                        r=values[1],
                        er=values[2],
                        bb=values[3],
                        so=values[4],
                        wp=values[5],
                        bk=values[6],
                        hbp=values[7],
                        ibb=values[8],
                        ab=values[9],
                        bf=values[10],
                        fo=values[11],
                        go=values[12],
                        np=values[13],
                        source_locator=f"GAME.NCA/San Diego State pitching/row[{pitching_row_number}]",
                    )
                )

    if "San Diego State" not in scores or opponent not in scores:
        raise ParseError("team scores are missing from GAME.NCA")
    _add_supplemental(batting_lines, parser.text_segments)
    return ParsedGame(
        game_id=_game_id(game_date, opponent),
        game_date=game_date,
        opponent=opponent,
        sdsu_score=scores["San Diego State"],
        opponent_score=scores[opponent],
        batting_lines=tuple(batting_lines),
        pitching_lines=tuple(pitching_lines),
        batting_totals=batting_totals,
        source_locator="GAME.NCA/game metadata and team score headings",
    )


def parse_recap(content: bytes) -> tuple[RecapPassage, ...]:
    parser = _RecapHTMLParser()
    parser.feed(_decode_html(content, "recap"))
    parser.close()

    start = next(
        (
            index
            for index, paragraph in enumerate(parser.paragraphs)
            if paragraph.startswith("In the completion for Friday's contest")
        ),
        None,
    )
    end = next(
        (
            index
            for index, paragraph in enumerate(parser.paragraphs)
            if paragraph.startswith("In Saturday's regularly schedule contest")
        ),
        None,
    )
    if start is None or end is None or start >= end:
        raise ParseError("cannot isolate February 17 passages in the combined recap")

    selected = parser.paragraphs[start:end]
    return tuple(
        RecapPassage(
            passage_order=order,
            text=text,
            source_locator=f"embed-html/p[{paragraph_index + 1}]",
        )
        for order, (paragraph_index, text) in enumerate(
            ((index, parser.paragraphs[index]) for index in range(start, end)), start=1
        )
    )
