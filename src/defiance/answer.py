"""Deterministic natural-language questions over the normalized 2017 corpus."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from importlib.resources import files
from pathlib import Path
import json
import re
import unicodedata

from .query import (
    QueryError,
    load_question_catalog,
    query_hitter_series_candidates,
    query_player_aggregate,
    query_player_boxed_totals,
    query_player_game,
    query_player_highlight_games,
    query_player_season,
    query_team_leader_rows,
    retrieve_article_passages,
    retrieve_play_by_play_passages,
)


ALIASES_PATH = files("defiance").joinpath("question_aliases.json")
ANSWER_STATUSES = frozenset(
    {
        "answered",
        "unknown_entity",
        "ambiguous_entity",
        "unsupported",
        "unavailable",
        "no_evidence",
        "off_topic",
    }
)


@dataclass(frozen=True)
class EvidenceReference:
    """One exact source location supporting an answer."""

    label: str
    source_id: str
    original_url: str
    source_locator: str
    raw_path: str


@dataclass(frozen=True)
class AnswerResult:
    """Product-level result for one independent question."""

    question: str
    status: str
    intent: str | None
    text: str
    evidence: tuple[EvidenceReference, ...] = ()
    suggestions: tuple[str, ...] = ()
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if self.status not in ANSWER_STATUSES:
            raise ValueError(f"invalid answer status: {self.status}")
        if self.status == "answered" and not self.evidence:
            raise ValueError("answered results require evidence")
        if self.status == "answered" and self.failure_reason is not None:
            raise ValueError("answered results cannot contain a failure reason")
        if self.status != "answered" and self.failure_reason is None:
            raise ValueError("non-answered results require a failure reason")

    def render(self) -> str:
        """Render the compact answer used by the CLI and future presentation layers."""
        lines = [self.text]
        source_urls: list[tuple[str, str]] = []
        seen_urls: set[str] = set()
        for reference in self.evidence:
            if reference.original_url in seen_urls:
                continue
            seen_urls.add(reference.original_url)
            source_urls.append((reference.label, reference.original_url))
        if source_urls:
            lines.extend(("", "Sources:"))
            for label, url in source_urls[:3]:
                lines.append(f"- {label}: {url}")
            if len(source_urls) > 3:
                lines.append(f"- {len(source_urls) - 3} additional supporting sources")
        if self.suggestions:
            lines.extend(("", "Try asking:"))
            lines.extend(f"- {suggestion}" for suggestion in self.suggestions)
        return "\n".join(lines)


@dataclass(frozen=True)
class MetricSpec:
    key: str
    discipline: str
    column: str
    label: str
    aliases: tuple[str, ...]
    value_kind: str = "integer"
    leader_direction: str = "max"
    scopes: tuple[str, ...] = ("season", "game", "aggregate", "leader")


METRICS = (
    MetricSpec(
        "batting_average",
        "batting",
        "batting_average",
        "batting average",
        ("batting average",),
        "average",
    ),
    MetricSpec("games", "batting", "games", "games", ("games played",)),
    MetricSpec("at_bats", "batting", "at_bats", "at-bats", ("at bats", "at-bats", "ab")),
    MetricSpec("runs", "batting", "runs", "runs", ("runs scored", "runs")),
    MetricSpec("hits", "batting", "hits", "hits", ("base hits", "hits")),
    MetricSpec("doubles", "batting", "doubles", "doubles", ("doubles", "double")),
    MetricSpec("triples", "batting", "triples", "triples", ("triples", "triple")),
    MetricSpec("home_runs", "batting", "home_runs", "home runs", ("home runs", "home run", "homers", "homer", "hr")),
    MetricSpec("runs_batted_in", "batting", "runs_batted_in", "RBI", ("runs batted in", "rbis", "rbi")),
    MetricSpec("total_bases", "batting", "total_bases", "total bases", ("total bases",)),
    MetricSpec("slugging_percentage", "batting", "slugging_percentage", "slugging percentage", ("slugging percentage", "slugging", "slg"), "average"),
    MetricSpec("walks", "batting", "walks", "walks", ("walks", "walk")),
    MetricSpec("hit_by_pitch", "batting", "hit_by_pitch", "times hit by pitch", ("hit by pitch", "times hit by pitch", "hbp")),
    MetricSpec("strikeouts", "batting", "strikeouts", "strikeouts", ("strikeouts", "strikeout", "times struck out")),
    MetricSpec("on_base_percentage", "batting", "on_base_percentage", "on-base percentage", ("on base percentage", "on-base percentage", "obp"), "average"),
    MetricSpec("stolen_bases", "batting", "stolen_bases", "stolen bases", ("stolen bases", "stolen base", "steals")),
    MetricSpec("earned_run_average", "pitching", "earned_run_average", "ERA", ("earned run average", "era"), "decimal", "min"),
    MetricSpec("wins", "pitching", "wins", "wins", ("pitching wins", "wins")),
    MetricSpec("losses", "pitching", "losses", "losses", ("pitching losses", "losses")),
    MetricSpec("appearances", "pitching", "appearances", "appearances", ("pitching appearances", "appearances")),
    MetricSpec("starts", "pitching", "starts", "starts", ("pitching starts", "starts")),
    MetricSpec("complete_games", "pitching", "complete_games", "complete games", ("complete games",)),
    MetricSpec("shutouts", "pitching", "shutouts", "shutouts", ("pitching shutouts", "shutouts")),
    MetricSpec("saves", "pitching", "saves", "saves", ("saves", "save")),
    MetricSpec("outs", "pitching", "outs", "innings", ("innings pitched", "innings", "ip"), "innings"),
    MetricSpec("hits", "pitching", "hits", "hits allowed", ("hits allowed",)),
    MetricSpec("runs", "pitching", "runs", "runs allowed", ("runs allowed",)),
    MetricSpec("earned_runs", "pitching", "earned_runs", "earned runs", ("earned runs", "er")),
    MetricSpec("walks", "pitching", "walks", "walks allowed", ("walks allowed",)),
    MetricSpec("strikeouts", "pitching", "strikeouts", "strikeouts", ("pitching strikeouts", "strikeouts", "strikeout", "ks")),
    MetricSpec("home_runs_allowed", "pitching", "home_runs_allowed", "home runs allowed", ("home runs allowed",)),
    MetricSpec("opponent_batting_average", "pitching", "opponent_batting_average", "opponent batting average", ("opponent batting average", "batting average against"), "average", "min"),
    MetricSpec("pitches", "pitching", "np", "pitches", ("pitch count", "pitches thrown", "number of pitches"), scopes=("game",)),
)


NARRATIVE_TOPICS = {
    "home run": ("home run", "homer", "homered"),
    "double": ("double", "doubled"),
    "triple": ("triple", "tripled"),
    "hit": ("hit", "single"),
    "rbi": ("RBI", "drove in"),
    "strikeout": ("strikeout", "struck out", "striking out"),
    "save": ("save",),
    "walk off": ("walk-off", "walk off"),
    "winning run": ("winning run", "game-winning", "go-ahead"),
    "catch": ("catch", "caught"),
    "award": ("award", "honor", "Player of the Week"),
    "championship": ("championship", "champion", "title"),
    "extra innings": ("extra innings", "13 innings"),
    "100th win": ("100th win", "100 victories"),
}

QUICK_HITTER_TOPICS = (
    "championship",
    "award",
    "walk off",
    "winning run",
    "home run",
    "save",
    "catch",
    "extra innings",
    "triple",
    "double",
)

BASEBALL_TERMS = frozenset(
    {
        "baseball",
        "batted",
        "batting",
        "box score",
        "era",
        "game",
        "games",
        "hit",
        "hits",
        "home run",
        "homer",
        "inning",
        "innings",
        "pitch",
        "pitched",
        "pitching",
        "rbi",
        "record",
        "recap",
        "run",
        "runs",
        "series",
        "strikeout",
        "strikeouts",
        "tournament",
        "win",
        "wins",
    }
)

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(character for character in value if not unicodedata.combining(character))
    value = value.replace("’", "'")
    value = re.sub(r"'s\b", "", value, flags=re.IGNORECASE)
    value = value.replace("'", "").replace(".", "")
    value = value.replace("-", " ")
    return re.sub(r"[^a-z0-9+]+", " ", value.casefold()).strip()


def _contains(text: str, phrase: str) -> bool:
    normalized = _normalize(phrase)
    return re.search(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", text) is not None


def _load_aliases() -> dict[str, object]:
    try:
        aliases = json.loads(ALIASES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QueryError(f"cannot load question aliases {ALIASES_PATH}: {exc}") from exc
    if not isinstance(aliases, dict) or aliases.get("schema_version") != 1:
        raise QueryError("question aliases must use schema version 1")
    return aliases


@dataclass(frozen=True)
class _EntityEntry:
    alias: str
    kind: str
    target: str
    label: str


@dataclass(frozen=True)
class _EntityMatch:
    start: int
    end: int
    kind: str
    target: str
    label: str


@dataclass(frozen=True)
class _Catalog:
    players: dict[str, dict[str, object]]
    staff: dict[str, dict[str, object]]
    games: tuple[dict[str, object], ...]
    groups: dict[str, dict[str, object]]
    group_games: dict[str, tuple[dict[str, object], ...]]
    records: dict[int, dict[str, object]]
    entries: tuple[_EntityEntry, ...]
    record_aliases: dict[int, tuple[str, ...]]


def _catalog(database_path: Path, aliases: dict[str, object]) -> _Catalog:
    raw = load_question_catalog(database_path)
    players = {str(row["player_id"]): row for row in raw["players"]}
    staff = {str(row["staff_id"]): row for row in raw["staff"]}
    games = tuple(raw["games"])
    groups = {str(row["group_id"]): row for row in raw["groups"]}
    game_by_id = {str(row["game_id"]): row for row in games}
    memberships: dict[str, list[dict[str, object]]] = {group_id: [] for group_id in groups}
    for membership in raw["memberships"]:
        game = dict(game_by_id[str(membership["game_id"])])
        game["group_order"] = membership["group_order"]
        game["membership_source_id"] = membership["source_id"]
        game["membership_source_locator"] = membership["source_locator"]
        memberships[str(membership["group_id"])].append(game)
    group_games = {
        group_id: tuple(sorted(rows, key=lambda row: int(row["group_order"])))
        for group_id, rows in memberships.items()
    }
    records = {int(row["record_order"]): row for row in raw["records"]}

    entries: list[_EntityEntry] = []
    for player_id, player in players.items():
        name = str(player["full_name"])
        entries.append(_EntityEntry(_normalize(name), "player", player_id, name))
    for staff_id, member in staff.items():
        name = str(member["full_name"])
        entries.append(_EntityEntry(_normalize(name), "staff", staff_id, name))

    player_surnames: dict[str, list[tuple[str, str]]] = {}
    for player_id, player in players.items():
        surname = _normalize(str(player["full_name"]).rsplit(" ", 1)[-1])
        player_surnames.setdefault(surname, []).append((player_id, str(player["full_name"])))
    for surname, candidates in player_surnames.items():
        for player_id, name in candidates:
            entries.append(_EntityEntry(surname, "player", player_id, name))

    staff_surnames: dict[str, list[tuple[str, str]]] = {}
    for staff_id, member in staff.items():
        surname = _normalize(str(member["full_name"]).rsplit(" ", 1)[-1])
        staff_surnames.setdefault(surname, []).append((staff_id, str(member["full_name"])))
    for surname, candidates in staff_surnames.items():
        for staff_id, name in candidates:
            entries.append(_EntityEntry(surname, "staff", staff_id, name))

    configured_players = aliases.get("players")
    configured_staff = aliases.get("staff")
    configured_opponents = aliases.get("opponents")
    configured_events = aliases.get("events")
    team_aliases = aliases.get("team")
    record_aliases = aliases.get("record_splits")
    if not all(
        isinstance(value, expected)
        for value, expected in (
            (configured_players, dict),
            (configured_staff, dict),
            (configured_opponents, dict),
            (configured_events, dict),
            (team_aliases, list),
            (record_aliases, dict),
        )
    ):
        raise QueryError("question alias sections have invalid types")

    def add_configured(
        configured: dict[str, object],
        available: set[str],
        kind: str,
        labels: dict[str, str],
    ) -> None:
        unknown = set(configured) - available
        if unknown:
            raise QueryError(f"question aliases reference unknown {kind}: {sorted(unknown)}")
        for target, values in configured.items():
            if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
                raise QueryError(f"aliases for {target} must be strings")
            for value in values:
                entries.append(_EntityEntry(_normalize(value), kind, target, labels[target]))

    add_configured(
        configured_players,
        set(players),
        "player",
        {key: str(value["full_name"]) for key, value in players.items()},
    )
    add_configured(
        configured_staff,
        set(staff),
        "staff",
        {key: str(value["full_name"]) for key, value in staff.items()},
    )
    canonical_opponents = {str(game["opponent"]) for game in games}
    add_configured(
        configured_opponents,
        canonical_opponents,
        "opponent",
        {opponent: opponent for opponent in canonical_opponents},
    )
    event_ids = {
        group_id for group_id, group in groups.items() if group["group_type"] == "event"
    }
    add_configured(
        configured_events,
        event_ids,
        "event",
        {group_id: str(groups[group_id]["label"]) for group_id in event_ids},
    )
    for team_alias in team_aliases:
        if not isinstance(team_alias, str):
            raise QueryError("team aliases must be strings")
        entries.append(_EntityEntry(_normalize(team_alias), "team", "sdsu", "San Diego State"))

    normalized_record_aliases: dict[int, tuple[str, ...]] = {}
    for order_text, values in record_aliases.items():
        try:
            order = int(order_text)
        except (TypeError, ValueError) as exc:
            raise QueryError(f"invalid record alias target: {order_text}") from exc
        if order not in records:
            raise QueryError(f"record aliases reference unknown row: {order}")
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise QueryError(f"record aliases for {order} must be strings")
        normalized_record_aliases[order] = tuple(_normalize(value) for value in values)
    if set(normalized_record_aliases) != set(records):
        raise QueryError("record aliases must cover every official record row")

    unique_entries = {
        (entry.alias, entry.kind, entry.target, entry.label): entry
        for entry in entries
        if entry.alias
    }
    return _Catalog(
        players=players,
        staff=staff,
        games=games,
        groups=groups,
        group_games=group_games,
        records=records,
        entries=tuple(
            sorted(
                unique_entries.values(),
                key=lambda entry: (-len(entry.alias), entry.kind, entry.target),
            )
        ),
        record_aliases=normalized_record_aliases,
    )


def _entity_matches(question: str, catalog: _Catalog) -> dict[str, list[_EntityMatch]]:
    candidates: list[_EntityMatch] = []
    for entry in catalog.entries:
        pattern = rf"(?<![a-z0-9]){re.escape(entry.alias)}(?![a-z0-9])"
        for match in re.finditer(pattern, question):
            candidates.append(
                _EntityMatch(match.start(), match.end(), entry.kind, entry.target, entry.label)
            )
    candidates.sort(key=lambda match: (-(match.end - match.start), match.start, match.kind))
    selected: list[_EntityMatch] = []
    for candidate in candidates:
        overlapping = [
            match
            for match in selected
            if candidate.start < match.end and match.start < candidate.end
        ]
        if not overlapping:
            selected.append(candidate)
        elif all(
            candidate.start == match.start and candidate.end == match.end
            for match in overlapping
        ):
            selected.append(candidate)
    result: dict[str, list[_EntityMatch]] = {}
    for match in sorted(selected, key=lambda item: (item.start, item.kind, item.target)):
        values = result.setdefault(match.kind, [])
        if all(existing.target != match.target for existing in values):
            values.append(match)
    return result


def _parse_dates(question: str) -> tuple[date, ...]:
    found: set[date] = set()
    for match in re.finditer(r"\b(2017)[ -](\d{1,2})[ -](\d{1,2})\b", question):
        try:
            found.add(date(int(match.group(1)), int(match.group(2)), int(match.group(3))))
        except ValueError:
            continue
    for match in re.finditer(
        rf"\b({'|'.join(MONTHS)})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:\s+2017)?\b",
        question,
    ):
        try:
            found.add(date(2017, MONTHS[match.group(1)], int(match.group(2))))
        except ValueError:
            continue
    for match in re.finditer(r"\b(\d{1,2})[ /](\d{1,2})(?:[ /](17|2017))?\b", question):
        try:
            found.add(date(2017, int(match.group(1)), int(match.group(2))))
        except ValueError:
            continue
    return tuple(sorted(found))


def _question_mentions_other_season(question: str) -> bool:
    return any(int(year) != 2017 for year in re.findall(r"\b(20\d{2})\b", question))


def _metric_matches(question: str) -> tuple[MetricSpec, ...]:
    matches: list[tuple[int, MetricSpec]] = []
    for metric in METRICS:
        for alias in metric.aliases:
            normalized = _normalize(alias)
            found = re.search(
                rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", question
            )
            if found:
                matches.append((len(normalized), metric))
    if not matches:
        return ()
    longest = max(length for length, _ in matches)
    unique: dict[tuple[str, str], MetricSpec] = {}
    for length, metric in matches:
        if length == longest:
            unique[(metric.discipline, metric.key)] = metric
    return tuple(unique.values())


def _narrative_topic(question: str) -> tuple[str, tuple[str, ...]] | None:
    matches = [
        (len(_normalize(topic)), topic, variants)
        for topic, variants in NARRATIVE_TOPICS.items()
        if _contains(question, topic)
    ]
    if not matches:
        return None
    _, topic, variants = max(matches)
    return topic, variants


def _labels(matches: list[_EntityMatch]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(match.label for match in matches))


def _single_person(
    original_question: str,
    matches: dict[str, list[_EntityMatch]],
    catalog: _Catalog,
    *,
    allow_staff: bool = False,
) -> tuple[str, str, dict[str, object]] | AnswerResult:
    people = list(matches.get("player", ()))
    if allow_staff:
        people.extend(matches.get("staff", ()))
    targets = {(match.kind, match.target): match for match in people}
    if not targets:
        unknown = _unknown_person_phrase(original_question)
        label = f"“{unknown}”" if unknown else "that person"
        return _failure(
            original_question,
            "unknown_entity",
            None,
            f"I couldn't find {label} on the 2017 San Diego State roster. Try the full player or staff name.",
            f"unknown_person:{unknown or 'missing'}",
            suggestions=(
                "How many home runs did Danny Sheehan hit in 2017?",
                "What were Brett Seeburger's pitching stats in 2017?",
            ),
        )
    if len(targets) > 1:
        names = tuple(sorted(match.label for match in targets.values()))
        joined = ", ".join(names[:-1]) + (f" or {names[-1]}" if len(names) > 1 else names[0])
        suggestions = tuple(
            f"What were {name}'s {'pitching' if name == 'Tre Brown' else 'batting'} stats in 2017?"
            for name in names[:2]
        )
        return _failure(
            original_question,
            "ambiguous_entity",
            None,
            f"That name could mean {joined}. Ask again with the full name.",
            "ambiguous_person:" + ",".join(target for _, target in sorted(targets)),
            suggestions=suggestions,
        )
    (kind, target), match = next(iter(targets.items()))
    row = catalog.players[target] if kind == "player" else catalog.staff[target]
    return kind, target, row


def _unknown_person_phrase(question: str) -> str | None:
    normalized = question.strip().rstrip("?.!")
    patterns = (
        r"(?i)what (?:were|are) (.+?)(?:'s|’s) (?:2017 |season |batting |pitching )?stats",
        r"(?i)how many .+? did (.+?) (?:have|hit|record|throw|pitch)",
        r"(?i)what did (.+?) (?:do|hit|bat|pitch)",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            candidate = match.group(1).strip()
            if 1 <= len(candidate.split()) <= 5:
                return candidate
    return None


def _opponent(
    original_question: str,
    matches: dict[str, list[_EntityMatch]],
) -> str | None | AnswerResult:
    opponents = matches.get("opponent", [])
    if len(opponents) > 1:
        return _failure(
            original_question,
            "ambiguous_entity",
            None,
            "The question names more than one opponent. Ask about one opponent at a time.",
            "multiple_opponents:" + ",".join(match.target for match in opponents),
        )
    return opponents[0].target if opponents else None


def _event(
    original_question: str,
    matches: dict[str, list[_EntityMatch]],
) -> str | None | AnswerResult:
    events = matches.get("event", [])
    if len(events) > 1:
        return _failure(
            original_question,
            "ambiguous_entity",
            None,
            "The question names more than one tournament. Ask about one event at a time.",
            "multiple_events:" + ",".join(match.target for match in events),
        )
    return events[0].target if events else None


def _location_qualifier(question: str) -> str | None:
    home = any(_contains(question, phrase) for phrase in ("home", "at home", "host"))
    road = any(_contains(question, phrase) for phrase in ("road", "away", "on the road"))
    if home and road:
        return "conflict"
    if home:
        return "home"
    if road:
        return "away"
    return None


def _series_candidates(
    question: str,
    catalog: _Catalog,
    opponent: str | None,
) -> tuple[dict[str, object], ...]:
    candidates = [
        group
        for group in catalog.groups.values()
        if group["group_type"] == "series"
        and (opponent is None or group["opponent"] == opponent)
    ]
    location = _location_qualifier(question)
    if location == "home":
        candidates = [group for group in candidates if "home series" in str(group["label"]).casefold()]
    elif location == "away":
        candidates = [group for group in candidates if "road series" in str(group["label"]).casefold()]
    parsed_dates = _parse_dates(question)
    if parsed_dates:
        candidates = [
            group
            for group in candidates
            if any(
                str(group["start_date"]) <= parsed.isoformat() <= str(group["end_date"])
                for parsed in parsed_dates
            )
        ]
    for month_name, month in MONTHS.items():
        if _contains(question, month_name):
            candidates = [
                group
                for group in candidates
                if int(str(group["start_date"])[5:7]) == month
                or int(str(group["end_date"])[5:7]) == month
            ]
    return tuple(sorted(candidates, key=lambda group: (str(group["start_date"]), str(group["group_id"]))))


def _resolve_series(
    original_question: str,
    question: str,
    catalog: _Catalog,
    opponent: str | None,
) -> dict[str, object] | AnswerResult:
    if _location_qualifier(question) == "conflict":
        return _failure(
            original_question,
            "ambiguous_entity",
            None,
            "The question says both home and road. Ask about one series location.",
            "conflicting_series_location",
        )
    candidates = _series_candidates(question, catalog, opponent)
    if not candidates:
        return _failure(
            original_question,
            "unknown_entity",
            None,
            "I couldn't match that to a reviewed 2017 series. Include the opponent and, when needed, home or road.",
            f"unknown_series:{opponent or 'missing_opponent'}",
        )
    if len(candidates) > 1:
        labels = ", ".join(str(candidate["label"]) for candidate in candidates)
        suggestions = tuple(
            f"What happened in the {candidate['label']}?" for candidate in candidates[:2]
        )
        return _failure(
            original_question,
            "ambiguous_entity",
            None,
            f"That could mean {labels}. Include home, road, or a date.",
            "ambiguous_series:" + ",".join(str(candidate["group_id"]) for candidate in candidates),
            suggestions=suggestions,
        )
    return candidates[0]


def _has_game_anchor(question: str) -> bool:
    return bool(
        _parse_dates(question)
        or any(_contains(question, weekday) for weekday in WEEKDAYS)
        or any(
            _contains(question, phrase)
            for phrase in ("game", "opener", "finale", "first game", "second game")
        )
    )


def _resolve_game(
    original_question: str,
    question: str,
    catalog: _Catalog,
    *,
    opponent: str | None,
    event_id: str | None,
    series: dict[str, object] | None = None,
) -> dict[str, object] | AnswerResult:
    candidates = list(catalog.games)
    if opponent is not None:
        candidates = [game for game in candidates if game["opponent"] == opponent]
    if event_id is not None:
        event_game_ids = {
            str(game["game_id"]) for game in catalog.group_games[event_id]
        }
        candidates = [game for game in candidates if game["game_id"] in event_game_ids]
    if series is not None:
        series_game_ids = {
            str(game["game_id"])
            for game in catalog.group_games[str(series["group_id"])]
        }
        candidates = [game for game in candidates if game["game_id"] in series_game_ids]
    parsed_dates = _parse_dates(question)
    if parsed_dates:
        date_values = {parsed.isoformat() for parsed in parsed_dates}
        candidates = [game for game in candidates if game["game_date"] in date_values]
    weekdays = [number for name, number in WEEKDAYS.items() if _contains(question, name)]
    if weekdays:
        candidates = [
            game
            for game in candidates
            if date.fromisoformat(str(game["game_date"])).weekday() in weekdays
        ]
    location = _location_qualifier(question)
    if location == "home":
        candidates = [game for game in candidates if game["designation"] == "vs" and not game["tournament"]]
    elif location == "away":
        candidates = [game for game in candidates if game["designation"] == "at" and not game["tournament"]]
    if any(_contains(question, phrase) for phrase in ("opener", "first game")) and candidates:
        first_order = min(int(game["schedule_order"]) for game in candidates)
        candidates = [game for game in candidates if int(game["schedule_order"]) == first_order]
    if any(_contains(question, phrase) for phrase in ("finale", "last game")) and candidates:
        last_order = max(int(game["schedule_order"]) for game in candidates)
        candidates = [game for game in candidates if int(game["schedule_order"]) == last_order]
    if _contains(question, "second game") and candidates:
        ordered = sorted(candidates, key=lambda game: int(game["schedule_order"]))
        candidates = ordered[1:2] if len(ordered) >= 2 else []
    if not candidates:
        return _failure(
            original_question,
            "unknown_entity",
            None,
            "I couldn't match those details to a 2017 San Diego State game.",
            "unknown_game",
        )
    if len(candidates) > 1:
        choices = ", ".join(
            f"{game['game_date']} vs. {game['opponent']}"
            for game in candidates[:6]
        )
        return _failure(
            original_question,
            "ambiguous_entity",
            None,
            f"That matches multiple games: {choices}. Include the exact date or series/event.",
            "ambiguous_game:" + ",".join(str(game["game_id"]) for game in candidates),
        )
    return candidates[0]


def _evidence(
    row: dict[str, object],
    label: str,
    *,
    source_key: str = "source_id",
    url_key: str = "original_url",
    locator_key: str = "source_locator",
    raw_key: str = "raw_path",
) -> EvidenceReference | None:
    values = (
        row.get(source_key),
        row.get(url_key),
        row.get(locator_key),
        row.get(raw_key),
    )
    if any(value is None for value in values):
        return None
    return EvidenceReference(
        label=label,
        source_id=str(values[0]),
        original_url=str(values[1]),
        source_locator=str(values[2]),
        raw_path=str(values[3]),
    )


def _dedupe_evidence(
    references: tuple[EvidenceReference | None, ...] | list[EvidenceReference | None],
) -> tuple[EvidenceReference, ...]:
    result: list[EvidenceReference] = []
    seen: set[tuple[str, str]] = set()
    for reference in references:
        if reference is None:
            continue
        key = (reference.source_id, reference.source_locator)
        if key in seen:
            continue
        seen.add(key)
        result.append(reference)
    return tuple(result)


def _answered(
    question: str,
    intent: str,
    text: str,
    evidence: tuple[EvidenceReference | None, ...] | list[EvidenceReference | None],
    *,
    suggestions: tuple[str, ...] = (),
) -> AnswerResult:
    return AnswerResult(
        question=question,
        status="answered",
        intent=intent,
        text=text,
        evidence=_dedupe_evidence(evidence),
        suggestions=suggestions,
    )


def _failure(
    question: str,
    status: str,
    intent: str | None,
    text: str,
    reason: str,
    *,
    evidence: tuple[EvidenceReference | None, ...] | list[EvidenceReference | None] = (),
    suggestions: tuple[str, ...] = (),
) -> AnswerResult:
    return AnswerResult(
        question=question,
        status=status,
        intent=intent,
        text=text,
        evidence=_dedupe_evidence(evidence),
        suggestions=suggestions,
        failure_reason=reason,
    )


def _innings(outs: int) -> str:
    return f"{outs // 3}.{outs % 3}"


def _average(hits: int, at_bats: int) -> str | None:
    if at_bats == 0:
        return None
    value = (Decimal(hits) / Decimal(at_bats)).quantize(
        Decimal("0.001"), rounding=ROUND_HALF_UP
    )
    rendered = f"{value:.3f}"
    return rendered[1:] if rendered.startswith("0") else rendered


def _era(earned_runs: int, outs: int) -> str | None:
    if outs == 0:
        return None
    value = (Decimal(earned_runs * 27) / Decimal(outs)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return f"{value:.2f}"


def _join_clauses(clauses: list[str]) -> str:
    if len(clauses) == 1:
        return clauses[0]
    if len(clauses) == 2:
        return f"{clauses[0]} and {clauses[1]}"
    return ", ".join(clauses[:-1]) + f", and {clauses[-1]}"


def _season_scope(question: str) -> str:
    return "conference" if any(
        _contains(question, phrase)
        for phrase in ("conference stats", "conference play", "mountain west stats")
    ) else "overall"


def _discipline_cue(question: str) -> str | None:
    pitching = any(
        _contains(question, phrase)
        for phrase in ("pitch", "pitched", "pitching", "on the mound", "allowed")
    )
    batting = any(
        _contains(question, phrase)
        for phrase in ("bat", "batted", "batting", "hit", "hitting", "at bat", "rbi")
    )
    if pitching and batting:
        return "both"
    if pitching:
        return "pitching"
    if batting:
        return "batting"
    return None


def _select_metric(
    question: str,
    metrics: tuple[MetricSpec, ...],
    *,
    available_disciplines: set[str] | None = None,
    scope: str,
) -> MetricSpec | None | str:
    candidates = [metric for metric in metrics if scope in metric.scopes]
    if not candidates:
        return None
    cue = _discipline_cue(question)
    if cue in {"batting", "pitching"}:
        candidates = [metric for metric in candidates if metric.discipline == cue]
    if available_disciplines:
        filtered = [
            metric for metric in candidates if metric.discipline in available_disciplines
        ]
        if filtered:
            candidates = filtered
    unique = {(metric.discipline, metric.key): metric for metric in candidates}
    if len(unique) == 1:
        return next(iter(unique.values()))
    return "ambiguous"


def _metric_text(name: str, row: dict[str, object], metric: MetricSpec, context: str) -> str:
    value = row[metric.column]
    if metric.value_kind == "innings":
        rendered = _innings(int(value))
    else:
        rendered = str(value)
    if metric.key == "home_runs":
        return f"{name} hit {rendered} home runs {context}."
    if metric.key == "hits" and metric.discipline == "batting":
        return f"{name} had {rendered} hits {context}."
    if metric.key == "strikeouts" and metric.discipline == "pitching":
        return f"{name} recorded {rendered} strikeouts {context}."
    if metric.key == "strikeouts":
        return f"{name} struck out {rendered} times {context}."
    if metric.key == "runs_batted_in":
        return f"{name} had {rendered} RBI {context}."
    if metric.key == "batting_average":
        return f"{name} hit {rendered} {context}."
    if metric.key == "earned_run_average":
        return f"{name} had a {rendered} ERA {context}."
    if metric.key == "outs":
        return f"{name} pitched {rendered} innings {context}."
    return f"{name} had {rendered} {metric.label} {context}."


def _batting_summary(name: str, row: dict[str, object], context: str) -> str:
    average = row.get("batting_average")
    if average is None:
        average = _average(int(row["hits"]), int(row["at_bats"]))
    line = f"{name} went {row['hits']}-for-{row['at_bats']}"
    if average is not None:
        line += f" ({average})"
    clauses = [f"{row['runs_batted_in']} RBI"]
    if row.get("home_runs") is not None:
        clauses.append(f"{row['home_runs']} home runs")
    return f"{line} with {_join_clauses(clauses)} {context}."


def _pitching_summary(name: str, row: dict[str, object], context: str) -> str:
    record = f"{row['wins']}-{row['losses']}"
    saves = int(row["saves"])
    saves_clause = f", and {saves} {'save' if saves == 1 else 'saves'}" if saves else ""
    strikeouts = int(row["strikeouts"])
    appearances = int(row["appearances"])
    return (
        f"{name} went {record} with a {row['earned_run_average']} ERA over "
        f"{_innings(int(row['outs']))} innings, with {strikeouts} "
        f"{'strikeout' if strikeouts == 1 else 'strikeouts'} in {appearances} "
        f"{'appearance' if appearances == 1 else 'appearances'}{saves_clause} {context}."
    )


def _game_batting_summary(name: str, row: dict[str, object], context: str) -> str:
    clauses = [f"{row['r']} runs", f"{row['rbi']} RBI"]
    for column, label in (
        ("home_runs", "home run"),
        ("triples", "triple"),
        ("doubles", "double"),
    ):
        value = row.get(column)
        if value:
            plural = "s" if int(value) != 1 else ""
            clauses.append(f"{value} {label}{plural}")
    return f"{name} went {row['h']}-for-{row['ab']} with {_join_clauses(clauses)} {context}."


def _game_pitching_summary(name: str, row: dict[str, object], context: str) -> str:
    decision = str(row["decision"]).split(",", 1)[0] if row.get("decision") else None
    result = (
        f"{name} pitched {_innings(int(row['outs']))} innings, allowing {row['r']} runs "
        f"({row['er']} earned) on {row['h']} hits with {row['bb']} walks and "
        f"{row['so']} strikeouts {context}"
    )
    if decision:
        result += f" and got the {decision}"
    return result + "."


def _record_text(game: dict[str, object]) -> tuple[str, str]:
    won = int(game["sdsu_score"]) > int(game["opponent_score"])
    outcome = "beat" if won else "lost to"
    score = f"{game['sdsu_score']}-{game['opponent_score']}"
    return outcome, score


def _strip_dateline(text: str) -> str:
    return re.sub(r"^[^-]{2,60}\s+-\s+", "", text).strip()


def _excerpt(text: str, sentences: int) -> str:
    cleaned = _strip_dateline(" ".join(text.split()))
    protected = re.sub(
        r"\b(?:Calif|Nev|N\.M|N\.C|Ariz|Jr|Sr|No|[A-Z])\.",
        lambda match: match.group(0).replace(".", "<DOT>"),
        cleaned,
    )
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", protected)
    return " ".join(parts[:sentences]).replace("<DOT>", ".").strip()


def _sentence_with_name(text: str, name: str) -> tuple[int, str] | None:
    cleaned = _strip_dateline(" ".join(text.split()))
    protected = re.sub(
        r"\b(?:Calif|Nev|N\.M|N\.C|Ariz|Jr|Sr|No|[A-Z])\.",
        lambda match: match.group(0).replace(".", "<DOT>"),
        cleaned,
    )
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", protected)
    full_name = _normalize(name)
    surname = _normalize(name.rsplit(" ", 1)[-1])
    for index, sentence in enumerate(sentences):
        restored = sentence.replace("<DOT>", ".").strip()
        normalized = _normalize(restored)
        if _contains(normalized, full_name) or _contains(normalized, surname):
            return index, restored
    return None


SEASON_TO_GAME_BATCH = {
    "at_bats": "batting_ab",
    "runs": "batting_r",
    "hits": "batting_h",
    "runs_batted_in": "batting_rbi",
    "walks": "batting_bb",
    "strikeouts": "batting_so",
    "doubles": "batting_doubles",
    "triples": "batting_triples",
    "home_runs": "batting_home_runs",
    "stolen_bases": "batting_stolen_bases",
}
PITCHING_TO_GAME_BATCH = {
    "outs": "pitching_outs",
    "hits": "pitching_h",
    "runs": "pitching_r",
    "earned_runs": "pitching_er",
    "walks": "pitching_bb",
    "strikeouts": "pitching_so",
    "wins": "pitching_wins",
    "losses": "pitching_losses",
    "saves": "pitching_saves",
    "pitches": "pitching_pitches",
}
SEASON_TO_GAME_LINE = {
    "at_bats": "ab",
    "runs": "r",
    "hits": "h",
    "runs_batted_in": "rbi",
    "walks": "bb",
    "strikeouts": "so",
    "doubles": "doubles",
    "triples": "triples",
    "home_runs": "home_runs",
    "stolen_bases": "stolen_bases",
}
PITCHING_TO_GAME_LINE = {
    "outs": "outs",
    "hits": "h",
    "runs": "r",
    "earned_runs": "er",
    "walks": "bb",
    "strikeouts": "so",
    "pitches": "np",
}
CORE_RESIDUAL_COLUMNS = {
    "batting": ("at_bats", "runs", "hits", "runs_batted_in", "walks", "strikeouts"),
    "pitching": (
        "outs",
        "hits",
        "runs",
        "earned_runs",
        "walks",
        "strikeouts",
        "wins",
        "losses",
        "saves",
    ),
}


def _season_answer(
    database_path: Path,
    original_question: str,
    question: str,
    player_id: str,
) -> AnswerResult:
    scope = _season_scope(question)
    data = query_player_season(database_path, player_id, scope=scope)
    player = data["player"]
    name = str(player["full_name"])
    available = {
        discipline
        for discipline in ("batting", "pitching")
        if data[discipline] is not None
    }
    metric = _select_metric(
        question,
        _metric_matches(question),
        available_disciplines=available,
        scope="season",
    )
    if metric == "ambiguous":
        return _failure(
            original_question,
            "unsupported",
            "player_season",
            "That statistic can mean batting or pitching. Say which one you mean.",
            "ambiguous_metric",
            suggestions=(
                f"What were {name}'s batting stats in 2017?",
                f"What were {name}'s pitching stats in 2017?",
            ),
        )
    scope_text = "in conference play in 2017" if scope == "conference" else "in 2017"
    if isinstance(metric, MetricSpec):
        row = data[metric.discipline]
        intent = f"season_player_{metric.discipline}"
        if row is None:
            return _answered(
                original_question,
                intent,
                f"SDSU's official {scope} season statistics do not list a {metric.discipline} line for {name}.",
                (_evidence(player, "2017 SDSU roster"),),
            )
        return _answered(
            original_question,
            intent,
            _metric_text(name, row, metric, scope_text),
            (_evidence(row, "2017 SDSU season statistics"),),
            suggestions=(
                "Who led San Diego State in home runs in 2017?"
                if metric.discipline == "batting"
                else "Who led San Diego State in saves in 2017?",
            ),
        )

    cue = _discipline_cue(question)
    requested = {cue} if cue in {"batting", "pitching"} else available
    summaries: list[str] = []
    evidence: list[EvidenceReference | None] = []
    for discipline in ("batting", "pitching"):
        if discipline not in requested:
            continue
        row = data[discipline]
        if row is None:
            summaries.append(
                f"SDSU's official {scope} season statistics do not list a {discipline} line for {name}."
            )
            evidence.append(_evidence(player, "2017 SDSU roster"))
        elif discipline == "batting":
            summaries.append(_batting_summary(name, row, scope_text))
            evidence.append(_evidence(row, "2017 SDSU season statistics"))
        else:
            summaries.append(_pitching_summary(name, row, scope_text))
            evidence.append(_evidence(row, "2017 SDSU season statistics"))
    if not summaries:
        return _answered(
            original_question,
            "player_season",
            f"SDSU's official season statistics do not list a batting or pitching line for {name}.",
            (_evidence(player, "2017 SDSU roster"),),
        )
    intent = (
        f"season_player_{cue}"
        if cue in {"batting", "pitching"}
        else "player_season"
    )
    return _answered(original_question, intent, " ".join(summaries), evidence)


def _game_answer(
    database_path: Path,
    original_question: str,
    question: str,
    player_id: str,
    game: dict[str, object],
) -> AnswerResult:
    data = query_player_game(database_path, player_id, str(game["game_id"]))
    player_name = next(
        str(match["full_name"])
        for match in load_question_catalog(database_path)["players"]
        if match["player_id"] == player_id
    )
    game_row = data["game"]
    game_evidence = _evidence(game_row, f"{game_row['game_date']} game source")
    if not game_row["has_box_score"]:
        return _failure(
            original_question,
            "unavailable",
            "single_game_player",
            f"SDSU's archive has no box score for the {game_row['game_date']} game against {game_row['opponent']}, so I can't give an exact line for {player_name}.",
            f"missing_box_score:{game_row['game_id']}",
            evidence=(game_evidence,),
        )
    available = {
        discipline
        for discipline in ("batting", "pitching")
        if data[discipline] is not None
    }
    metric = _select_metric(
        question,
        _metric_matches(question),
        available_disciplines=available,
        scope="game",
    )
    if metric == "ambiguous":
        return _failure(
            original_question,
            "unsupported",
            "single_game_player",
            "That statistic can mean batting or pitching. Say which one you mean.",
            "ambiguous_metric",
        )
    context = f"against {game_row['opponent']} on {game_row['game_date']}"
    if isinstance(metric, MetricSpec):
        row = data[metric.discipline]
        line_key = (
            SEASON_TO_GAME_LINE.get(metric.key)
            if metric.discipline == "batting"
            else PITCHING_TO_GAME_LINE.get(metric.key)
        )
        if row is None:
            return _answered(
                original_question,
                "single_game_player",
                f"{player_name} did not have a {metric.discipline} line {context}.",
                (game_evidence,),
            )
        if line_key is None:
            return _failure(
                original_question,
                "unsupported",
                "single_game_player",
                f"That season statistic is not available as a supported single-game field.",
                f"unsupported_game_metric:{metric.key}",
            )
        if row[line_key] is None:
            return _failure(
                original_question,
                "unavailable",
                "single_game_player",
                f"The box score does not report {metric.label} for {player_name} in that game.",
                f"null_game_metric:{game_row['game_id']}:{metric.key}",
                evidence=(_evidence(row, "SDSU box score"),),
            )
        metric_row = dict(row)
        metric_row[metric.column] = row[line_key]
        return _answered(
            original_question,
            "single_game_player",
            _metric_text(player_name, metric_row, metric, context),
            (_evidence(row, "SDSU box score"),),
        )

    cue = _discipline_cue(question)
    requested = {cue} if cue in {"batting", "pitching"} else available
    summaries: list[str] = []
    evidence: list[EvidenceReference | None] = []
    if "batting" in requested and data["batting"] is not None:
        summaries.append(_game_batting_summary(player_name, data["batting"], context))
        evidence.append(_evidence(data["batting"], "SDSU box score"))
    if "pitching" in requested and data["pitching"] is not None:
        summaries.append(_game_pitching_summary(player_name, data["pitching"], context))
        evidence.append(_evidence(data["pitching"], "SDSU box score"))
    if not summaries:
        return _answered(
            original_question,
            "single_game_player",
            f"{player_name} did not appear in SDSU's batting or pitching lines {context}.",
            (game_evidence,),
        )
    return _answered(
        original_question,
        "single_game_player",
        " ".join(summaries),
        evidence,
        suggestions=(
            f"What happened in the {game_row['game_date']} game against {game_row['opponent']}?",
        ),
    )


def _residual_proves_zero(
    database_path: Path,
    player_id: str,
    discipline: str,
) -> bool:
    season = query_player_season(database_path, player_id, scope="overall")[discipline]
    if season is None:
        return True
    boxed = query_player_boxed_totals(database_path, player_id)[discipline]
    return all(
        int(season[column]) - int(boxed[column]) == 0
        for column in CORE_RESIDUAL_COLUMNS[discipline]
    )


def _aggregate_references(
    data: dict[str, object],
    *,
    discipline: str,
    group: dict[str, object] | None,
) -> tuple[EvidenceReference, ...]:
    references: list[EvidenceReference | None] = []
    if group is not None:
        references.append(_evidence(group, str(group["label"])))
    locator_key = f"{discipline}_source_locator"
    for game in data["games"]:
        if game["box_source_id"] is not None:
            locator = game.get(locator_key) or game["score_source_locator"]
            row = dict(game)
            row["box_locator"] = locator
            references.append(
                _evidence(
                    row,
                    f"{game['game_date']} box score",
                    source_key="box_source_id",
                    url_key="box_original_url",
                    locator_key="box_locator",
                    raw_key="box_raw_path",
                )
            )
        else:
            references.append(
                _evidence(
                    game,
                    f"{game['game_date']} game source",
                    source_key="score_source_id",
                    url_key="score_original_url",
                    locator_key="score_source_locator",
                    raw_key="score_raw_path",
                )
            )
    return _dedupe_evidence(references)


def _aggregate_metric_value(
    aggregate: dict[str, object], metric: MetricSpec
) -> object | None:
    if metric.discipline == "batting":
        if metric.key == "batting_average":
            return _average(int(aggregate["batting_h"]), int(aggregate["batting_ab"]))
        key = SEASON_TO_GAME_BATCH.get(metric.key)
        if key is None:
            return None
        unknown_key = {
            "doubles": "unknown_doubles",
            "triples": "unknown_triples",
            "home_runs": "unknown_home_runs",
            "stolen_bases": "unknown_stolen_bases",
        }.get(metric.key)
        if unknown_key and int(aggregate[unknown_key]) > 0:
            return None
        return aggregate[key]
    if metric.key == "earned_run_average":
        return _era(int(aggregate["pitching_er"]), int(aggregate["pitching_outs"]))
    key = PITCHING_TO_GAME_BATCH.get(metric.key)
    if key is None:
        return None
    if metric.key == "pitches" and int(aggregate["unknown_pitches"]) > 0:
        return None
    return aggregate[key]


def _aggregate_answer(
    database_path: Path,
    original_question: str,
    question: str,
    player_id: str,
    *,
    opponent: str | None = None,
    group: dict[str, object] | None = None,
) -> AnswerResult:
    group_id = str(group["group_id"]) if group is not None else None
    data = query_player_aggregate(
        database_path,
        player_id,
        opponent=opponent,
        group_id=group_id,
    )
    aggregate = data["aggregate"]
    season = query_player_season(database_path, player_id, scope="overall")
    name = str(season["player"]["full_name"])
    available = {
        discipline
        for discipline in ("batting", "pitching")
        if season[discipline] is not None
    }
    metric = _select_metric(
        question,
        _metric_matches(question),
        available_disciplines=available,
        scope="aggregate",
    )
    if metric == "ambiguous":
        return _failure(
            original_question,
            "unsupported",
            "series_player" if group else "opponent_player",
            "That statistic can mean batting or pitching. Say which one you mean.",
            "ambiguous_metric",
        )
    cue = _discipline_cue(question)
    if isinstance(metric, MetricSpec):
        disciplines = {metric.discipline}
    elif cue in {"batting", "pitching"}:
        disciplines = {cue}
    else:
        disciplines = {
            discipline
            for discipline in available
            if int(aggregate[f"{discipline}_games"]) > 0
        }
        if not disciplines:
            disciplines = available
    if not disciplines:
        disciplines = {"batting", "pitching"}
    missing_games = int(aggregate["selected_games"]) - int(aggregate["box_games"])
    for discipline in disciplines:
        if missing_games and not _residual_proves_zero(database_path, player_id, discipline):
            missing_ids = [
                str(game["game_id"])
                for game in data["games"]
                if game["box_source_id"] is None
            ]
            scope_label = str(group["label"]) if group is not None else str(opponent)
            scope_preposition = "in" if group is not None else "against"
            return _failure(
                original_question,
                "unavailable",
                "series_player" if group else "opponent_player",
                f"SDSU's archive is missing a box score {scope_preposition} {scope_label}, so I can't give an exact {discipline} aggregate for {name}.",
                "missing_box_score:" + ",".join(missing_ids),
                evidence=_aggregate_references(data, discipline=discipline, group=group),
            )
    context = (
        f"in the {group['label']}"
        if group is not None
        else f"against {opponent} in 2017"
    )
    intent = "series_player" if group is not None else "opponent_player"
    if isinstance(metric, MetricSpec):
        value = _aggregate_metric_value(aggregate, metric)
        if value is None:
            return _failure(
                original_question,
                "unavailable",
                intent,
                f"The available box scores do not report enough information to calculate {metric.label} exactly {context}.",
                f"null_aggregate_metric:{metric.key}",
                evidence=_aggregate_references(
                    data, discipline=metric.discipline, group=group
                ),
            )
        metric_row = {metric.column: value}
        return _answered(
            original_question,
            intent,
            _metric_text(name, metric_row, metric, context),
            _aggregate_references(data, discipline=metric.discipline, group=group),
        )

    summaries: list[str] = []
    evidence: list[EvidenceReference | None] = []
    if "batting" in disciplines:
        hits = int(aggregate["batting_h"])
        at_bats = int(aggregate["batting_ab"])
        average = _average(hits, at_bats)
        line = f"{name} went {hits}-for-{at_bats}"
        if average is not None:
            line += f" ({average})"
        line += f" with {aggregate['batting_rbi']} RBI {context}"
        if group is None:
            line += f" across {aggregate['batting_games']} games"
        summaries.append(line + ".")
        evidence.extend(_aggregate_references(data, discipline="batting", group=group))
    if "pitching" in disciplines:
        outs = int(aggregate["pitching_outs"])
        era = _era(int(aggregate["pitching_er"]), outs)
        record = f"{aggregate['pitching_wins']}-{aggregate['pitching_losses']}"
        line = (
            f"{name} pitched {_innings(outs)} innings with a {era or 'undefined'} ERA, "
            f"{aggregate['pitching_er']} earned runs, {aggregate['pitching_so']} strikeouts, "
            f"and a {record} record {context}"
        )
        if group is None:
            line += f" across {aggregate['pitching_games']} games"
        summaries.append(line + ".")
        evidence.extend(_aggregate_references(data, discipline="pitching", group=group))
    return _answered(
        original_question,
        intent,
        " ".join(summaries),
        evidence,
        suggestions=(
            f"What happened in the {group['label']}?"
            if group is not None
            else f"What was San Diego State's record against {opponent} in 2017?",
        ),
    )


def _best_series_answer(
    database_path: Path,
    original_question: str,
    player_id: str,
) -> AnswerResult:
    data = query_hitter_series_candidates(database_path, player_id)
    season = data["season"]
    player = query_player_season(database_path, player_id)["player"]
    name = str(player["full_name"])
    if season is None:
        return _failure(
            original_question,
            "unavailable",
            "hitter_best_series",
            f"SDSU's official season statistics do not list a batting line for {name}.",
            f"no_season_batting:{player_id}",
            evidence=(_evidence(player, "2017 SDSU roster"),),
        )
    residual_ab = int(season["at_bats"]) - int(data["boxed"]["at_bats"])
    residual_h = int(season["hits"]) - int(data["boxed"]["hits"])
    if residual_ab < 0 or residual_h < 0 or residual_h > residual_ab:
        return _failure(
            original_question,
            "unavailable",
            "hitter_best_series",
            f"The season and available game totals do not support a safe best-series comparison for {name}.",
            f"invalid_best_series_residual:{player_id}",
            evidence=(_evidence(season, "2017 SDSU season statistics"),),
        )
    complete = [
        row
        for row in data["series"]
        if int(row["member_games"]) == int(row["box_games"])
        and int(row["at_bats"]) > 0
    ]
    if not complete:
        return _failure(
            original_question,
            "unavailable",
            "hitter_best_series",
            f"There is no complete qualifying series line for {name}.",
            f"no_complete_series:{player_id}",
            evidence=(_evidence(season, "2017 SDSU season statistics"),),
        )
    best = [complete[0]]
    for candidate in complete[1:]:
        left = int(candidate["hits"]) * int(best[0]["at_bats"])
        right = int(best[0]["hits"]) * int(candidate["at_bats"])
        if left > right:
            best = [candidate]
        elif left == right:
            best.append(candidate)
    best_row = best[0]
    incomplete = [
        row
        for row in data["series"]
        if int(row["member_games"]) != int(row["box_games"])
    ]
    for candidate in incomplete:
        upper_hits = int(candidate["hits"]) + residual_h
        upper_at_bats = int(candidate["at_bats"]) + residual_h
        if upper_at_bats == 0:
            continue
        if (
            upper_hits * int(best_row["at_bats"])
            >= int(best_row["hits"]) * upper_at_bats
        ):
            return _failure(
                original_question,
                "unavailable",
                "hitter_best_series",
                f"A missing box score could change {name}'s highest series batting average, so I can't name a best series safely.",
                f"unresolved_best_series:{candidate['group_id']}",
                evidence=(
                    _evidence(season, "2017 SDSU season statistics"),
                    _evidence(candidate, str(candidate["label"])),
                ),
            )
    average = _average(int(best_row["hits"]), int(best_row["at_bats"]))
    labels = _join_clauses([str(row["label"]) for row in best])
    if len(best) == 1:
        text = (
            f"{name}'s best series by batting average was the {labels}: "
            f"{best_row['hits']}-for-{best_row['at_bats']} ({average})."
        )
    else:
        text = f"{name}'s best series batting average was {average}, tied in {labels}."
    winner = query_player_aggregate(
        database_path, player_id, group_id=str(best_row["group_id"])
    )
    return _answered(
        original_question,
        "hitter_best_series",
        text,
        (
            _evidence(season, "2017 SDSU season statistics"),
            *_aggregate_references(winner, discipline="batting", group=best_row),
        ),
        suggestions=(f"What happened in the {best_row['label']}?",),
    )


def _leader_answer(
    database_path: Path,
    original_question: str,
    question: str,
) -> AnswerResult:
    metric = _select_metric(
        question,
        _metric_matches(question),
        scope="leader",
    )
    if metric is None:
        return _failure(
            original_question,
            "unsupported",
            "team_leader",
            "Name the batting or pitching category for the team-leader question.",
            "missing_leader_metric",
            suggestions=(
                "Who led San Diego State in home runs in 2017?",
                "Who led San Diego State in saves in 2017?",
            ),
        )
    if metric == "ambiguous":
        return _failure(
            original_question,
            "unsupported",
            "team_leader",
            "That leader category can mean batting or pitching. Say which one you mean.",
            "ambiguous_leader_metric",
        )
    assert isinstance(metric, MetricSpec)
    rows = query_team_leader_rows(
        database_path,
        discipline=metric.discipline,
        metric=metric.column,
        scope=_season_scope(question),
    )
    if not rows:
        return _failure(
            original_question,
            "unavailable",
            "team_leader",
            "The official season table does not contain that leader category.",
            f"empty_leader_metric:{metric.key}",
        )
    values = [Decimal(str(row["value"])) for row in rows]
    best_value = min(values) if metric.leader_direction == "min" else max(values)
    leaders = [
        row for row in rows if Decimal(str(row["value"])) == best_value
    ]
    names = _join_clauses([str(row["full_name"]) for row in leaders])
    value = str(leaders[0]["value"])
    scope_text = "conference play" if _season_scope(question) == "conference" else "2017"
    if len(leaders) == 1:
        text = f"{names} led San Diego State in {metric.label} with {value} in {scope_text}."
    else:
        text = f"{names} tied for the San Diego State lead in {metric.label} with {value} in {scope_text}."
    if metric.value_kind in {"average", "decimal"}:
        sample = (
            f"{leaders[0]['at_bats']} at-bats"
            if metric.discipline == "batting"
            else f"{_innings(int(leaders[0]['outs']))} innings"
        )
        text = text[:-1] + f" ({sample})."
    return _answered(
        original_question,
        "team_leader",
        text,
        [_evidence(row, "2017 SDSU season statistics") for row in leaders],
        suggestions=("What was San Diego State's record in 2017?",),
    )


def _record_split(
    question: str,
    catalog: _Catalog,
) -> dict[str, object]:
    matches: list[tuple[int, int]] = []
    for order, aliases in catalog.record_aliases.items():
        for alias in aliases:
            if _contains(question, alias):
                matches.append((len(alias), order))
    if matches:
        _, order = max(matches)
        return catalog.records[order]
    return catalog.records[1]


def _record_description(record: dict[str, object]) -> str:
    order = int(record["record_order"])
    descriptions = {
        3: "non-conference",
        4: "home",
        5: "road",
        6: "neutral-site",
        7: "day-game",
        8: "night-game",
        9: "record against left-handed starters",
        10: "record against right-handed starters",
        11: "one-run game",
        12: "two-run game",
        13: "games decided by five or more runs",
        14: "extra-inning",
        15: "shutout",
        16: "record when scoring 0-2 runs",
        17: "record when scoring 3-5 runs",
        18: "record when scoring 6-9 runs",
        19: "record when scoring 10 or more runs",
        20: "record when allowing 0-2 runs",
        21: "record when allowing 3-5 runs",
        22: "record when allowing 6-9 runs",
        23: "record when allowing 10 or more runs",
        24: "record when scoring in the first inning",
        25: "record when the opponent scored in the first inning",
        26: "record when scoring first",
        27: "record when the opponent scored first",
    }
    return descriptions.get(order, str(record["label"]))


def _team_record_answer(
    original_question: str,
    question: str,
    catalog: _Catalog,
    *,
    opponent: str | None,
    group: dict[str, object] | None,
    event_id: str | None,
) -> AnswerResult:
    if group is not None or event_id is not None:
        selected_group = group or catalog.groups[str(event_id)]
        games = catalog.group_games[str(selected_group["group_id"])]
        scores = ", ".join(
            f"{game['game_date']} {game['sdsu_score']}-{game['opponent_score']}"
            for game in games
        )
        text = (
            f"San Diego State went {selected_group['sdsu_wins']}-{selected_group['sdsu_losses']} "
            f"in the {selected_group['label']}. Scores: {scores}."
        )
        evidence: list[EvidenceReference | None] = [
            _evidence(selected_group, str(selected_group["label"]))
        ]
        evidence.extend(
            _evidence(game, f"{game['game_date']} result") for game in games
        )
        return _answered(
            original_question,
            "event_result" if event_id else "series_result",
            text,
            evidence,
        )
    if opponent is not None:
        games = [game for game in catalog.games if game["opponent"] == opponent]
        wins = sum(int(game["sdsu_score"]) > int(game["opponent_score"]) for game in games)
        losses = len(games) - wins
        return _answered(
            original_question,
            "opponent_record",
            f"San Diego State went {wins}-{losses} against {opponent} in 2017.",
            [_evidence(game, f"{game['game_date']} result") for game in games],
        )
    record = _record_split(question, catalog)
    label = str(record["label"])
    if int(record["record_order"]) == 1:
        text = f"San Diego State went {record['wins']}-{record['losses']} in 2017."
    elif int(record["record_order"]) == 2:
        text = f"San Diego State went {record['wins']}-{record['losses']} in conference play in 2017."
    else:
        description = _record_description(record)
        if description.startswith("record ") or description.startswith("games "):
            text = f"San Diego State's {description} was {record['wins']}-{record['losses']} in 2017."
        else:
            text = f"San Diego State's {description} record was {record['wins']}-{record['losses']} in 2017."
    return _answered(
        original_question,
        "team_record",
        text,
        (_evidence(record, "2017 SDSU season statistics"),),
        suggestions=("Who led San Diego State in home runs in 2017?",),
    )


def _game_result_answer(
    original_question: str,
    game: dict[str, object],
) -> AnswerResult:
    outcome, score = _record_text(game)
    text = (
        f"San Diego State {outcome} {game['opponent']} {score} on {game['game_date']}."
    )
    return _answered(
        original_question,
        "game_result",
        text,
        (_evidence(game, f"{game['game_date']} result"),),
        suggestions=(
            f"What happened in the {game['game_date']} game against {game['opponent']}?",
        ),
    )


def _first_game_recap(database_path: Path, game_id: str) -> dict[str, object] | None:
    rows = retrieve_article_passages(database_path, game_id=game_id, limit=100)
    recap = [
        row
        for row in rows
        if row["block_type"] == "narrative"
        and str(row["text"]).count("|") < 2
        and f"{game_id}:recap" in (row["game_relationships"] or "").split(",")
    ]
    return min(recap, key=lambda row: (str(row["source_id"]), int(row["passage_order"]))) if recap else None


def _game_recap_answer(
    database_path: Path,
    original_question: str,
    game: dict[str, object],
) -> AnswerResult:
    passage = _first_game_recap(database_path, str(game["game_id"]))
    if passage is None:
        return _failure(
            original_question,
            "no_evidence",
            "game_recap",
            f"I found the {game['game_date']} game against {game['opponent']}, but no linked recap passage supports a narrative answer.",
            f"no_game_recap:{game['game_id']}",
            evidence=(_evidence(game, f"{game['game_date']} result"),),
        )
    outcome, score = _record_text(game)
    text = (
        f"San Diego State {outcome} {game['opponent']} {score}. "
        f"SDSU's recap says: {_excerpt(str(passage['text']), 2)}"
    )
    return _answered(
        original_question,
        "game_recap",
        text,
        (
            _evidence(game, f"{game['game_date']} result"),
            _evidence(passage, "SDSU game recap"),
        ),
        suggestions=(
            f"What was the result of the {game['game_date']} game against {game['opponent']}?",
        ),
    )


def _group_narrative_answer(
    database_path: Path,
    original_question: str,
    catalog: _Catalog,
    group: dict[str, object],
) -> AnswerResult:
    games = catalog.group_games[str(group["group_id"])]
    passages: list[tuple[dict[str, object], dict[str, object]]] = []
    for game in games:
        passage = _first_game_recap(database_path, str(game["game_id"]))
        if passage is None:
            return _failure(
                original_question,
                "no_evidence",
                "event_recap" if group["group_type"] == "event" else "series_recap",
                f"I found the {group['label']}, but the {game['game_date']} game has no linked recap passage.",
                f"no_group_game_recap:{game['game_id']}",
                evidence=(_evidence(group, str(group["label"])),),
            )
        passages.append((game, passage))
    record = f"{group['sdsu_wins']}-{group['sdsu_losses']}"
    evidence: list[EvidenceReference | None] = [_evidence(group, str(group["label"]))]
    if group["group_type"] == "event":
        game, passage = passages[-1]
        scores = ", ".join(
            f"{member['sdsu_score']}-{member['opponent_score']} vs. {member['opponent']}"
            for member in games
        )
        text = (
            f"San Diego State went {record} in the {group['label']} ({scores}). "
            f"The final-game recap says: {_excerpt(str(passage['text']), 2)}"
        )
        evidence.extend(_evidence(member, f"{member['game_date']} result") for member in games)
        evidence.append(_evidence(passage, "SDSU final-game recap"))
        intent = "event_recap"
    else:
        bullets = []
        for game, passage in passages:
            outcome, score = _record_text(game)
            bullets.append(
                f"{game['game_date']}: {outcome} {game['opponent']} {score}; "
                f"{_excerpt(str(passage['text']), 1)}"
            )
            evidence.extend(
                (
                    _evidence(game, f"{game['game_date']} result"),
                    _evidence(passage, f"{game['game_date']} recap"),
                )
            )
        text = f"San Diego State went {record} in the {group['label']}. " + " ".join(bullets)
        intent = "series_recap"
    return _answered(
        original_question,
        intent,
        text,
        evidence,
        suggestions=(
            f"What was San Diego State's record in the {group['label']}?",
        ),
    )


def _person_narrative_answer(
    database_path: Path,
    original_question: str,
    question: str,
    person_kind: str,
    person_id: str,
    person: dict[str, object],
    *,
    game: dict[str, object] | None,
    group: dict[str, object] | None,
    opponent: str | None,
) -> AnswerResult:
    topic = _narrative_topic(question)
    if game is None and group is None and opponent is None and topic is None:
        return _failure(
            original_question,
            "unsupported",
            "person_narrative",
            "Include a game, series, tournament, opponent, or specific baseball moment with the person's full name.",
            "unbounded_person_narrative",
        )
    selector: dict[str, object] = {}
    if person_kind == "player":
        selector["player_id"] = person_id
    else:
        selector["staff_id"] = person_id
    if game is not None:
        selector["game_id"] = str(game["game_id"])
    elif group is not None:
        selector["group_id"] = str(group["group_id"])
    elif opponent is not None:
        selector["opponent"] = opponent
    elif person_kind == "player" and topic and topic[0] == "award":
        selector["season"] = 2017

    article_rows: list[dict[str, object]] = []
    variants = topic[1] if topic else ()
    if variants:
        for variant in variants:
            article_rows.extend(
                retrieve_article_passages(
                    database_path,
                    **selector,
                    terms=(variant,),
                    limit=20,
                )
            )
    else:
        article_rows.extend(
            retrieve_article_passages(database_path, **selector, limit=100)
        )
    unique_articles = {
        (str(row["source_id"]), int(row["passage_order"])): row
        for row in article_rows
        if row["block_type"] == "narrative"
    }
    selected_articles = list(unique_articles.values())
    if game is not None:
        game_id = str(game["game_id"])
        selected_articles = [
            row
            for row in selected_articles
            if f"{game_id}:recap" in (row["game_relationships"] or "").split(",")
        ]
    selected_articles.sort(key=lambda row: (str(row["source_id"]), int(row["passage_order"])))

    play_rows: list[dict[str, object]] = []
    if not selected_articles and person_kind == "player" and (game or group or opponent) and variants:
        play_selector: dict[str, object] = {"player_id": person_id}
        if game is not None:
            play_selector["game_id"] = str(game["game_id"])
        elif group is not None:
            play_selector["group_id"] = str(group["group_id"])
        elif opponent is not None:
            play_selector["opponent"] = opponent
        for variant in variants:
            play_rows.extend(
                retrieve_play_by_play_passages(
                    database_path,
                    **play_selector,
                    terms=(variant,),
                    limit=20,
                )
            )
        play_rows = list(
            {
                (str(row["game_id"]), int(row["sequence"])): row
                for row in play_rows
            }.values()
        )
        play_rows.sort(key=lambda row: (str(row["game_id"]), int(row["sequence"])))

    if not selected_articles and not play_rows:
        scope = (
            f"the {game['game_date']} game against {game['opponent']}"
            if game is not None
            else f"the {group['label']}"
            if group is not None
            else f"games against {opponent}"
            if opponent is not None
            else "the 2017 season"
        )
        scope_evidence = (
            _evidence(game, f"{game['game_date']} result")
            if game is not None
            else _evidence(group, str(group["label"]))
            if group is not None
            else None
        )
        return _failure(
            original_question,
            "no_evidence",
            "person_narrative",
            f"I found {person['full_name']} and {scope}, but no linked SDSU passage supports that narrative answer.",
            f"no_person_narrative:{person_kind}:{person_id}",
            evidence=(
                _evidence(person, "2017 SDSU roster"),
                scope_evidence,
            ),
        )

    if selected_articles:
        chosen = selected_articles[:2]
        excerpts = [_excerpt(str(row["text"]), 2) for row in chosen]
        text = f"SDSU's archive says: {' '.join(excerpts)}"
        evidence = [_evidence(row, "SDSU article") for row in chosen]
    else:
        chosen = play_rows[:2]
        excerpts = [str(row["text"]) for row in chosen]
        text = f"SDSU's play-by-play says: {' '.join(excerpts)}"
        evidence = [_evidence(row, "SDSU play-by-play") for row in chosen]
    return _answered(
        original_question,
        "person_narrative",
        text,
        evidence,
    )


def _exact_full_name_person(
    question: str,
    catalog: _Catalog,
) -> tuple[str, str, dict[str, object]] | None:
    for kind, people in (("player", catalog.players), ("staff", catalog.staff)):
        for person_id, person in people.items():
            if question == _normalize(str(person["full_name"])):
                return kind, person_id, person
    return None


def _looks_like_full_name_entry(question: str) -> bool:
    return bool(re.fullmatch(r"[a-z]+(?: [a-z]+){1,4}", question))


def _notable_player_passage(
    database_path: Path,
    player_id: str,
    name: str,
) -> tuple[dict[str, object], str] | None:
    candidates: list[tuple[int, str, int, int, dict[str, object], str]] = []
    for row in retrieve_article_passages(
        database_path, player_id=player_id, limit=100
    ):
        if row["block_type"] != "narrative" or str(row["text"]).count("|") >= 2:
            continue
        matched = _sentence_with_name(str(row["text"]), name)
        if matched is None:
            continue
        sentence_index, sentence = matched
        if any(marker in sentence for marker in ("Ã", "â")):
            continue
        normalized = _normalize(sentence)
        score = sum(_contains(normalized, topic) for topic in QUICK_HITTER_TOPICS)
        if score:
            candidates.append(
                (
                    -score,
                    str(row["source_id"]),
                    int(row["passage_order"]),
                    sentence_index,
                    row,
                    sentence,
                )
            )
    if not candidates:
        return None
    selected = min(candidates)
    return selected[4], selected[5]


def _ranked_game(
    rows: list[dict[str, object]],
    *,
    discipline: str,
    secondary: bool = False,
) -> dict[str, object] | None:
    if discipline == "batting":
        eligible = [
            row
            for row in rows
            if any(int(row[column]) > 0 for column in ("r", "h", "rbi"))
        ]
        if secondary:
            eligible = [row for row in eligible if int(row["rbi"]) > 0]
            key = lambda row: (
                -int(row["rbi"]),
                -int(row["h"]),
                -int(row["r"]),
                int(row["schedule_order"]),
                str(row["game_id"]),
            )
        else:
            key = lambda row: (
                -int(row["h"]),
                -int(row["rbi"]),
                -int(row["r"]),
                -int(row["ab"]),
                int(row["schedule_order"]),
                str(row["game_id"]),
            )
    else:
        eligible = [
            row
            for row in rows
            if any(int(row[column]) > 0 for column in ("outs", "h", "r", "er", "so"))
        ]
        if secondary:
            key = lambda row: (
                -int(row["outs"]),
                -int(row["so"]),
                int(row["er"]),
                int(row["schedule_order"]),
                str(row["game_id"]),
            )
        else:
            key = lambda row: (
                -int(row["so"]),
                -int(row["outs"]),
                int(row["er"]),
                int(row["schedule_order"]),
                str(row["game_id"]),
            )
    return min(eligible, key=key) if eligible else None


def _player_quick_hitters(
    database_path: Path,
    original_question: str,
    player_id: str,
    player: dict[str, object],
    catalog: _Catalog,
) -> AnswerResult:
    name = str(player["full_name"])
    candidates: list[tuple[str, str, tuple[EvidenceReference, ...]]] = []

    passage_match = _notable_player_passage(database_path, player_id, name)
    if passage_match is not None:
        passage, excerpt = passage_match
        reference = _evidence(passage, "SDSU article")
        if excerpt and reference is not None:
            candidates.append(
                (
                    f"narrative:{passage['source_id']}:{passage['passage_order']}",
                    f"SDSU's archive says: {excerpt}",
                    (reference,),
                )
            )

    season = query_player_season(database_path, player_id)
    season_batting = season["batting"]
    useful_batting = season_batting is not None and any(
        int(season_batting[column]) > 0
        for column in ("hits", "runs", "runs_batted_in")
    )
    if season_batting is not None and int(season_batting["hits"]) > 0:
        best_series = _best_series_answer(database_path, original_question, player_id)
        if best_series.status == "answered":
            candidates.append(
                ("best-series", best_series.text, best_series.evidence)
            )

    game_lines = query_player_highlight_games(database_path, player_id)
    ranked_rows = (
        ("batting-game", _ranked_game(game_lines["batting"], discipline="batting")),
        ("pitching-game", _ranked_game(game_lines["pitching"], discipline="pitching")),
        (
            "batting-rbi-game",
            _ranked_game(game_lines["batting"], discipline="batting", secondary=True),
        ),
        (
            "pitching-longest-game",
            _ranked_game(game_lines["pitching"], discipline="pitching", secondary=True),
        ),
    )
    game_by_id = {str(game["game_id"]): game for game in catalog.games}
    for kind, row in ranked_rows:
        if row is None:
            continue
        game_id = str(row["game_id"])
        game = game_by_id[game_id]
        summary = _game_answer(
            database_path,
            original_question,
            "how did the player hit"
            if kind.startswith("batting")
            else "how did the player pitch",
            player_id,
            game,
        )
        if summary.status == "answered":
            candidates.append((f"game:{game_id}", summary.text, summary.evidence))

    selected: list[tuple[str, tuple[EvidenceReference, ...]]] = []
    seen_keys: set[str] = set()
    seen_text: set[str] = set()
    for key, text, evidence in candidates:
        normalized_text = _normalize(text)
        if key in seen_keys or normalized_text in seen_text:
            continue
        seen_keys.add(key)
        seen_text.add(normalized_text)
        selected.append((text, evidence))
        if len(selected) == 5:
            break

    if len(selected) < 3:
        season_question = "what were the player stats"
        if season["pitching"] is not None and not useful_batting:
            season_question = "what were the player pitching stats"
        elif season_batting is not None and season["pitching"] is None:
            season_question = "what were the player batting stats"
        season_answer = _season_answer(
            database_path,
            original_question,
            season_question,
            player_id,
        )
        normalized_text = _normalize(season_answer.text)
        if season_answer.status == "answered" and normalized_text not in seen_text:
            selected.append((season_answer.text, season_answer.evidence))
            seen_text.add(normalized_text)

    if not game_lines["batting"] and not game_lines["pitching"]:
        roster_text = (
            f"SDSU's 2017 roster listed {name} as No. {player['jersey_number']}, "
            f"{player['position']}, {player['class_year']}, "
            f"from {str(player['hometown']).rstrip('.')}."
        )
        normalized_text = _normalize(roster_text)
        reference = _evidence(player, "2017 SDSU roster")
        if normalized_text not in seen_text and reference is not None:
            selected.insert(0, (roster_text, (reference,)))

    evidence = [reference for _, references in selected for reference in references]
    lines = "\n".join(f"- {text}" for text, _ in selected[:5])
    suggestions = [
        f"What were {name}'s pitching stats in 2017?"
        if season["pitching"] is not None and not useful_batting
        else f"What were {name}'s 2017 stats?"
    ]
    if season_batting is not None and int(season_batting["hits"]) > 0:
        suggestions.append(f"What was {name}'s best series?")
    return _answered(
        original_question,
        "player_quick_hitters",
        f"A few things from {name}'s 2017 season:\n{lines}",
        evidence,
        suggestions=tuple(suggestions),
    )


def _staff_quick_hitters(
    database_path: Path,
    original_question: str,
    staff: dict[str, object],
    catalog: _Catalog,
) -> AnswerResult:
    name = str(staff["full_name"])
    records = {
        str(record["label"]).casefold(): record for record in catalog.records.values()
    }
    overall = records.get("overall")
    conference = records.get("conference")
    mountain_west = catalog.groups.get("event-2017-mountain-west-tournament")
    ncaa = catalog.groups.get("event-2017-ncaa-tournament")

    bullets: list[tuple[str, tuple[EvidenceReference | None, ...]]] = []
    if overall is not None and conference is not None:
        bullets.append(
            (
                "The 2017 team finished "
                f"{overall['wins']}-{overall['losses']} overall and "
                f"{conference['wins']}-{conference['losses']} in conference play.",
                (
                    _evidence(overall, "2017 SDSU season statistics"),
                    _evidence(conference, "2017 SDSU conference statistics"),
                ),
            )
        )
    elif overall is not None:
        bullets.append(
            (
                f"The 2017 team finished {overall['wins']}-{overall['losses']} overall.",
                (_evidence(overall, "2017 SDSU season statistics"),),
            )
        )

    if mountain_west is not None:
        mountain_west_games = catalog.group_games.get(
            str(mountain_west["group_id"]), ()
        )
        mountain_west_final = mountain_west_games[-1] if mountain_west_games else None
        mountain_west_recap = (
            _first_game_recap(database_path, str(mountain_west_final["game_id"]))
            if mountain_west_final is not None
            else None
        )
        bullets.append(
            (
                "The 2017 team went "
                f"{mountain_west['sdsu_wins']}-{mountain_west['sdsu_losses']} in the "
                "Mountain West Tournament and won the championship.",
                (
                    _evidence(mountain_west, "Mountain West Tournament"),
                    _evidence(mountain_west_final, "Mountain West championship game")
                    if mountain_west_final
                    else None,
                    _evidence(mountain_west_recap, "SDSU championship recap")
                    if mountain_west_recap
                    else None,
                ),
            )
        )

    if ncaa is not None:
        ncaa_games = catalog.group_games.get(str(ncaa["group_id"]), ())
        ucla = next((game for game in ncaa_games if game["opponent"] == "UCLA"), None)
        ucla_recap = (
            _first_game_recap(database_path, str(ucla["game_id"]))
            if ucla is not None
            else None
        )
        ncaa_text = (
            "The 2017 team went "
            f"{ncaa['sdsu_wins']}-{ncaa['sdsu_losses']} in the NCAA Tournament"
        )
        if ucla is not None:
            ncaa_text += ", including a 3-2, 13-inning win over UCLA"
        bullets.append(
            (
                f"{ncaa_text}.",
                (
                    _evidence(ncaa, "NCAA Tournament"),
                    _evidence(ucla, "2017-06-03 UCLA result") if ucla else None,
                    _evidence(ucla_recap, "SDSU UCLA recap") if ucla_recap else None,
                ),
            )
        )
    evidence: list[EvidenceReference | None] = [_evidence(staff, "2017 SDSU staff")]
    for _, references in bullets:
        evidence.extend(references)
    lines = "\n".join(f"- {text}" for text, _ in bullets)
    return _answered(
        original_question,
        "staff_quick_hitters",
        f"2017 team context for {name}:\n{lines}",
        evidence,
        suggestions=(
            "What happened in the Mountain West Tournament?",
            "What was San Diego State's record in 2017?",
        ),
    )


def _validated_suggestions(
    database_path: Path,
    result: AnswerResult,
) -> AnswerResult:
    valid: list[str] = []
    for suggestion in result.suggestions:
        if suggestion.casefold() == result.question.strip().casefold():
            continue
        candidate = _answer_question(database_path, suggestion, include_suggestions=False)
        if candidate.status == "answered":
            valid.append(suggestion)
        if len(valid) == 2:
            break
    return replace(result, suggestions=tuple(valid))


def _is_narrative(question: str) -> bool:
    return any(
        _contains(question, phrase)
        for phrase in (
            "what happened",
            "recap",
            "what did sdsu say",
            "what does sdsu say",
            "what did the recap say",
            "moment",
            "notable",
            "remember",
        )
    )


def _is_leader(question: str) -> bool:
    return bool(
        re.search(r"\bwho\b.*\b(?:led|lead|most|highest|lowest|fewest)\b", question)
        or _contains(question, "team leader")
    )


def _is_result_or_record(question: str) -> bool:
    return any(
        _contains(question, phrase)
        for phrase in (
            "record",
            "result",
            "score",
            "did sdsu win",
            "did san diego state win",
            "how did sdsu do",
            "how did san diego state do",
            "how did we do",
        )
    )


def _is_unsupported_baseball(question: str) -> bool:
    advanced = (
        "runners in scoring position",
        "risp",
        "with runners on",
        "two or more hits",
        "count based",
        "pitch count when",
    )
    subjective = (
        "funniest player",
        "locker room",
        "best player",
        "best pitcher",
        "best game",
        "favorite player",
    )
    conditional_player = re.search(r"\brecord when\b.*\b(?:player|sheehan|trejo|brown)\b", question)
    return any(_contains(question, phrase) for phrase in (*advanced, *subjective)) or bool(conditional_player)


def _looks_like_player_question(question: str) -> bool:
    return bool(
        _metric_matches(question)
        or _contains(question, "stats")
        or re.search(r"\bwhat did\b.+\b(?:do|hit|bat|pitch)\b", question)
        or re.search(r"\bhow did\b.+\b(?:hit|bat|pitch)\b", question)
    )


def _answer_question(
    database_path: Path,
    original_question: str,
    *,
    include_suggestions: bool,
) -> AnswerResult:
    if not isinstance(original_question, str) or not original_question.strip():
        result = _failure(
            str(original_question),
            "unsupported",
            None,
            "Ask one complete question about the 2017 San Diego State baseball season.",
            "empty_question",
        )
        return result
    question = _normalize(original_question)
    if _question_mentions_other_season(question):
        result = _failure(
            original_question,
            "unsupported",
            None,
            "Defiance currently covers only the 2017 San Diego State baseball season.",
            "season_out_of_scope",
        )
        return result
    aliases = _load_aliases()
    catalog = _catalog(database_path, aliases)
    matches = _entity_matches(question, catalog)
    opponent = _opponent(original_question, matches)
    if isinstance(opponent, AnswerResult):
        return _validated_suggestions(database_path, opponent) if include_suggestions else opponent
    event_id = _event(original_question, matches)
    if isinstance(event_id, AnswerResult):
        return _validated_suggestions(database_path, event_id) if include_suggestions else event_id

    full_name_person = _exact_full_name_person(question, catalog)
    if full_name_person is not None:
        kind, person_id, person = full_name_person
        result = (
            _player_quick_hitters(
                database_path,
                original_question,
                person_id,
                person,
                catalog,
            )
            if kind == "player"
            else _staff_quick_hitters(
                database_path,
                original_question,
                person,
                catalog,
            )
        )
        return _validated_suggestions(database_path, result) if include_suggestions else result

    if any(_contains(question, phrase) for phrase in ("that game", "that series", "what about", "how about")):
        result = _failure(
            original_question,
            "unsupported",
            None,
            "Each question stands alone. Include the player, opponent, game, or series in the question.",
            "missing_conversational_context",
            suggestions=("What was San Diego State's record in 2017?",),
        )
        return _validated_suggestions(database_path, result) if include_suggestions else result

    if _is_unsupported_baseball(question):
        result = _failure(
            original_question,
            "unsupported",
            None,
            "That baseball question is outside the supported V1 categories. I can answer season, game, opponent, series, leader, record, result, and anchored recap questions.",
            "unsupported_baseball_category",
            suggestions=(
                "Who led San Diego State in home runs in 2017?",
                "What was San Diego State's record in 2017?",
            ),
        )
        return _validated_suggestions(database_path, result) if include_suggestions else result

    result: AnswerResult
    if _contains(question, "best series"):
        person = _single_person(original_question, matches, catalog)
        if isinstance(person, AnswerResult):
            result = person
        elif person[0] != "player":
            result = _failure(
                original_question,
                "unsupported",
                "hitter_best_series",
                "Best-series questions are supported only for 2017 hitters.",
                "staff_best_series",
            )
        else:
            result = _best_series_answer(database_path, original_question, person[1])
    elif _is_leader(question):
        result = _leader_answer(database_path, original_question, question)
    elif _is_narrative(question):
        person_matches = matches.get("player", []) + matches.get("staff", [])
        explicit_series = _contains(question, "series")
        game_anchor = _has_game_anchor(question)
        group: dict[str, object] | None = None
        game: dict[str, object] | None = None
        if event_id is not None:
            group = catalog.groups[event_id]
        elif explicit_series or (opponent is not None and not game_anchor):
            resolved = _resolve_series(original_question, question, catalog, opponent)
            if isinstance(resolved, AnswerResult):
                result = resolved
                return _validated_suggestions(database_path, result) if include_suggestions else result
            group = resolved
        elif game_anchor or opponent is not None:
            resolved_game = _resolve_game(
                original_question,
                question,
                catalog,
                opponent=opponent,
                event_id=event_id,
            )
            if isinstance(resolved_game, AnswerResult):
                result = resolved_game
                return _validated_suggestions(database_path, result) if include_suggestions else result
            game = resolved_game
        if person_matches:
            person = _single_person(original_question, matches, catalog, allow_staff=True)
            if isinstance(person, AnswerResult):
                result = person
            else:
                result = _person_narrative_answer(
                    database_path,
                    original_question,
                    question,
                    person[0],
                    person[1],
                    person[2],
                    game=game,
                    group=group,
                    opponent=opponent,
                )
        elif group is not None:
            result = _group_narrative_answer(database_path, original_question, catalog, group)
        elif game is not None:
            result = _game_recap_answer(database_path, original_question, game)
        else:
            result = _failure(
                original_question,
                "unsupported",
                None,
                "Include an exact game, series, tournament, player, or staff member for a narrative question.",
                "unbounded_narrative",
            )
    elif _is_result_or_record(question):
        if event_id is not None:
            result = _team_record_answer(
                original_question,
                question,
                catalog,
                opponent=None,
                group=None,
                event_id=event_id,
            )
        elif _contains(question, "series"):
            resolved = _resolve_series(original_question, question, catalog, opponent)
            if isinstance(resolved, AnswerResult):
                result = resolved
            else:
                result = _team_record_answer(
                    original_question,
                    question,
                    catalog,
                    opponent=None,
                    group=resolved,
                    event_id=None,
                )
        elif opponent is not None and _has_game_anchor(question):
            resolved_game = _resolve_game(
                original_question,
                question,
                catalog,
                opponent=opponent,
                event_id=None,
            )
            result = (
                resolved_game
                if isinstance(resolved_game, AnswerResult)
                else _game_result_answer(original_question, resolved_game)
            )
        elif opponent is not None:
            result = _team_record_answer(
                original_question,
                question,
                catalog,
                opponent=opponent,
                group=None,
                event_id=None,
            )
        elif _contains(question, "record"):
            result = _team_record_answer(
                original_question,
                question,
                catalog,
                opponent=None,
                group=None,
                event_id=None,
            )
        else:
            result = _failure(
                original_question,
                "unsupported",
                None,
                "Include a game, series, tournament, opponent, or the word record.",
                "missing_result_scope",
            )
    elif _looks_like_player_question(question) or matches.get("player"):
        person = _single_person(original_question, matches, catalog)
        if isinstance(person, AnswerResult):
            result = person
        else:
            player_id = person[1]
            if _contains(question, "series"):
                resolved = _resolve_series(original_question, question, catalog, opponent)
                if isinstance(resolved, AnswerResult):
                    result = resolved
                else:
                    result = _aggregate_answer(
                        database_path,
                        original_question,
                        question,
                        player_id,
                        group=resolved,
                    )
            elif _has_game_anchor(question) and (opponent is not None or _parse_dates(question)):
                resolved_game = _resolve_game(
                    original_question,
                    question,
                    catalog,
                    opponent=opponent,
                    event_id=event_id,
                )
                result = (
                    resolved_game
                    if isinstance(resolved_game, AnswerResult)
                    else _game_answer(
                        database_path,
                        original_question,
                        question,
                        player_id,
                        resolved_game,
                    )
                )
            elif opponent is not None:
                result = _aggregate_answer(
                    database_path,
                    original_question,
                    question,
                    player_id,
                    opponent=opponent,
                )
            else:
                result = _season_answer(database_path, original_question, question, player_id)
    elif _looks_like_full_name_entry(question):
        result = _failure(
            original_question,
            "unknown_entity",
            None,
            "I couldn't find that full name on the 2017 San Diego State roster or staff list.",
            f"unknown_person:{question}",
            suggestions=(
                "Danny Sheehan",
                "Mark Martinez",
            ),
        )
    else:
        baseball = any(_contains(question, term) for term in BASEBALL_TERMS)
        if baseball:
            result = _failure(
                original_question,
                "unsupported",
                None,
                "I understand this as a baseball question, but it does not match a supported deterministic question pattern.",
                "unsupported_pattern",
            )
        else:
            result = _failure(
                original_question,
                "off_topic",
                None,
                "I'm staying in my lane: the 2017 San Diego State baseball season.",
                "off_topic",
                suggestions=("What was San Diego State's record in 2017?",),
            )
    return _validated_suggestions(database_path, result) if include_suggestions else result


def answer_question(database_path: Path, question: str) -> AnswerResult:
    """Answer one standalone 2017 SDSU baseball question without model assistance."""
    return _answer_question(database_path, question, include_suggestions=True)
