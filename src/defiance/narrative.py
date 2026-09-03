"""Deterministic relationships for preserved narrative evidence."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import json
import re
from typing import TYPE_CHECKING

from .corpus_parse import person_key
from .db import ValidationError

if TYPE_CHECKING:
    from .corpus_db import CorpusData


NARRATIVE_CONFIG_PATH = Path("config/2017/narrative.json")
BODY_BLOCK_TYPES = {"heading", "narrative"}


@dataclass(frozen=True)
class NarrativeRelationships:
    article_games: tuple[tuple[str, int, str, str], ...]
    article_players: tuple[tuple[str, int, str, str], ...]
    article_staff: tuple[tuple[str, int, str, str], ...]
    play_by_play_players: tuple[tuple[str, int, str, str], ...]
    group_sources: tuple[tuple[str, str, str], ...]
    season_sources: tuple[tuple[int, str, str], ...]


def load_narrative_config(repository_root: Path) -> dict[str, object]:
    path = repository_root / NARRATIVE_CONFIG_PATH
    try:
        config = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot load narrative configuration {path}: {exc}") from exc
    if not isinstance(config, dict) or config.get("schema_version") != 1:
        raise ValidationError("narrative configuration must use schema version 1")
    return config


def _mentions(text: str, name: str) -> bool:
    parts = [re.escape(part) for part in name.split()]
    pattern = rf"(?<![A-Za-z]){'\\s+'.join(parts)}(?![A-Za-z])"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def _body_passages(data: CorpusData, source_id: str):
    return tuple(
        passage
        for passage in data.articles[source_id]
        if passage.block_type in BODY_BLOCK_TYPES
    )


def _shared_recap_links(
    data: CorpusData,
) -> tuple[dict[str, dict[str, set[str]]], set[str]]:
    entries = data.narrative.get("shared_recaps")
    if not isinstance(entries, list):
        raise ValidationError("narrative shared_recaps must be a list")
    mappings: dict[str, dict[str, set[str]]] = {}
    shared_source_ids: set[str] = set()
    game_recap_sources = {
        str(game["game_id"]): str(game["recap_source_id"])
        for game in data.manifest["games"]
    }
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValidationError("shared recap review entry must be an object")
        source_id = str(entry.get("source_id", ""))
        games = entry.get("games")
        excluded = entry.get("excluded_body_locators")
        if not source_id or source_id in mappings or not isinstance(games, dict):
            raise ValidationError(f"invalid shared recap review for {source_id!r}")
        if not isinstance(excluded, dict) or not all(excluded.values()):
            raise ValidationError(f"shared recap {source_id} exclusions need reasons")
        if source_id not in data.articles:
            raise ValidationError(f"shared recap {source_id} is not an article source")
        available = {
            passage.source_locator: passage
            for passage in data.articles[source_id]
        }
        reviewed: set[str] = set(excluded)
        normalized_games: dict[str, set[str]] = {}
        for game_id, locators in games.items():
            game_id = str(game_id)
            if game_recap_sources.get(game_id) != source_id:
                raise ValidationError(
                    f"shared recap {source_id} is not the recap for {game_id}"
                )
            if not isinstance(locators, list) or not locators:
                raise ValidationError(
                    f"shared recap {source_id} has no reviewed passages for {game_id}"
                )
            locator_set = {str(locator) for locator in locators}
            if len(locator_set) != len(locators):
                raise ValidationError(
                    f"shared recap {source_id} repeats a locator for {game_id}"
                )
            normalized_games[game_id] = locator_set
            reviewed.update(locator_set)
        unknown = reviewed - available.keys()
        if unknown:
            raise ValidationError(
                f"shared recap {source_id} reviews unknown locators: {sorted(unknown)}"
            )
        non_body = {
            locator
            for locator in reviewed
            if available[locator].block_type not in BODY_BLOCK_TYPES
        }
        if non_body:
            raise ValidationError(
                f"shared recap {source_id} maps non-body locators: {sorted(non_body)}"
            )
        body_locators = {
            passage.source_locator for passage in _body_passages(data, source_id)
        }
        if reviewed != body_locators:
            missing = sorted(body_locators - reviewed)
            extra = sorted(reviewed - body_locators)
            raise ValidationError(
                f"shared recap {source_id} review is incomplete: "
                f"missing={missing}, extra={extra}"
            )
        mappings[source_id] = normalized_games
        shared_source_ids.add(source_id)

    recap_counts: dict[str, int] = defaultdict(int)
    for source_id in game_recap_sources.values():
        recap_counts[source_id] += 1
    actual_shared = {source_id for source_id, count in recap_counts.items() if count > 1}
    if shared_source_ids != actual_shared:
        raise ValidationError(
            "shared recap review does not exactly cover multi-game recap sources"
        )
    return mappings, shared_source_ids


def _article_game_relationships(data: CorpusData) -> list[tuple[str, int, str, str]]:
    shared, shared_source_ids = _shared_recap_links(data)
    links: set[tuple[str, int, str, str]] = set()
    games = data.manifest["games"]
    assert isinstance(games, list)
    passage_by_locator = {
        source_id: {passage.source_locator: passage for passage in passages}
        for source_id, passages in data.articles.items()
    }

    for game in games:
        game_id = str(game["game_id"])
        source_id = str(game["recap_source_id"])
        if source_id in shared_source_ids:
            locators = shared[source_id][game_id]
            passages = (passage_by_locator[source_id][locator] for locator in locators)
        else:
            passages = iter(_body_passages(data, source_id))
        links.update(
            (source_id, passage.passage_order, game_id, "recap")
            for passage in passages
        )

    source_by_id = {
        str(source["source_id"]): source for source in data.manifest["sources"]
    }
    games_by_date: dict[str, list[str]] = defaultdict(list)
    for game in games:
        games_by_date[str(game["game_date"])].append(str(game["game_id"]))
    for source_id in sorted(data.articles):
        source = source_by_id[source_id]
        if source["classification"] != "game_or_series_context":
            continue
        match = re.search(r"-news-(\d{4}-\d{2}-\d{2})-", source_id)
        if not match:
            continue
        for game_id in games_by_date.get(match.group(1), ()):
            links.update(
                (source_id, passage.passage_order, game_id, "context")
                for passage in _body_passages(data, source_id)
            )
    return sorted(links)


def _article_person_relationships(
    data: CorpusData,
) -> tuple[list[tuple[str, int, str, str]], list[tuple[str, int, str, str]]]:
    player_links: set[tuple[str, int, str, str]] = set()
    staff_links: set[tuple[str, int, str, str]] = set()
    for source_id in sorted(data.articles):
        passages = _body_passages(data, source_id)
        established_players = {
            player.player_id: player
            for player in data.players
            if any(_mentions(passage.text, player.full_name) for passage in passages)
        }
        established_staff_surnames = {
            member.full_name.rsplit(" ", 1)[-1].casefold()
            for member in data.staff
            if any(_mentions(passage.text, member.full_name) for passage in passages)
        }
        established_by_surname: dict[str, list[object]] = defaultdict(list)
        for player in established_players.values():
            established_by_surname[player.full_name.rsplit(" ", 1)[-1].casefold()].append(
                player
            )
        for passage in passages:
            for player in data.players:
                if _mentions(passage.text, player.full_name):
                    player_links.add(
                        (source_id, passage.passage_order, player.player_id, "full_name")
                    )
                    continue
                surname = player.full_name.rsplit(" ", 1)[-1]
                candidates = established_by_surname.get(surname.casefold(), ())
                if (
                    len(candidates) == 1
                    and candidates[0].player_id == player.player_id
                    and surname.casefold() not in established_staff_surnames
                    and _mentions(passage.text, surname)
                ):
                    player_links.add(
                        (
                            source_id,
                            passage.passage_order,
                            player.player_id,
                            "source_scoped_surname",
                        )
                    )
            for member in data.staff:
                if _mentions(passage.text, member.full_name):
                    staff_links.add(
                        (source_id, passage.passage_order, member.staff_id, "exact_full_name")
                    )
    return sorted(player_links), sorted(staff_links)


def _play_by_play_relationships(data: CorpusData) -> list[tuple[str, int, str, str]]:
    player_by_key = {person_key(player.full_name): player for player in data.players}
    links: set[tuple[str, int, str, str]] = set()
    for game_id, box in data.box_scores.items():
        participant_keys = {
            person_key(line.player_name)
            for line in (*box.batting_lines, *box.pitching_lines)
        }
        participants = [player_by_key[key] for key in participant_keys]
        by_surname: dict[str, list[object]] = defaultdict(list)
        for player in participants:
            by_surname[player.full_name.rsplit(" ", 1)[-1].casefold()].append(player)
        for passage in box.play_by_play:
            if passage.batting_team != "San Diego State":
                continue
            for surname, players in by_surname.items():
                pattern = rf"(?<![A-Z]){re.escape(surname)}(?:,([A-Z])\.)?(?![A-Z])"
                matches = re.findall(pattern, passage.text, flags=re.IGNORECASE)
                for initial in matches:
                    if initial:
                        candidates = [
                            player
                            for player in players
                            if player.full_name[0].casefold() == initial.casefold()
                        ]
                    else:
                        candidates = players
                    if len(candidates) == 1:
                        links.add(
                            (
                                game_id,
                                passage.sequence,
                                candidates[0].player_id,
                                "game_scoped_token",
                            )
                        )
    return sorted(links)


def _group_source_relationships(data: CorpusData) -> list[tuple[str, str, str]]:
    links: set[tuple[str, str, str]] = set()
    groups = data.manifest["schedule_groups"]
    assert isinstance(groups, list)
    group_by_id = {str(group["group_id"]): group for group in groups}

    # A series source is direct evidence only when the reviewed group provenance
    # resolves to the exact preserved passage. Absence is valid and yields no link.
    for group in groups:
        if group["group_type"] != "series":
            continue
        source_id = str(group["source_id"])
        if source_id not in data.articles:
            continue
        locators = {passage.source_locator for passage in data.articles[source_id]}
        if str(group["source_locator"]) in locators:
            links.add((str(group["group_id"]), source_id, "series_context"))

    event_sources = data.narrative.get("event_sources")
    if not isinstance(event_sources, dict):
        raise ValidationError("narrative event_sources must be an object")
    for group_id, source_ids in event_sources.items():
        group = group_by_id.get(str(group_id))
        if not group or group["group_type"] != "event":
            raise ValidationError(f"narrative event source has invalid group {group_id}")
        if not isinstance(source_ids, list) or not source_ids:
            raise ValidationError(f"narrative event {group_id} has no reviewed sources")
        for source_id in source_ids:
            source_id = str(source_id)
            if source_id not in data.articles:
                raise ValidationError(
                    f"narrative event {group_id} references non-article {source_id}"
                )
            links.add((str(group_id), source_id, "event_context"))
    return sorted(links)


def _season_source_relationships(data: CorpusData) -> list[tuple[int, str, str]]:
    overrides = data.narrative.get("season_source_overrides")
    if not isinstance(overrides, dict):
        raise ValidationError("narrative season_source_overrides must be an object")
    links: set[tuple[int, str, str]] = set()
    for source in data.manifest["sources"]:
        source_id = str(source["source_id"])
        if source_id not in data.articles:
            continue
        classification = str(source["classification"])
        relationship = None
        if classification == "season_honor":
            relationship = "honor"
        elif classification == "postseason_context":
            relationship = "postseason_context"
        if source_id in overrides:
            relationship = str(overrides[source_id])
        if relationship not in {"honor", "postseason_context"}:
            if source_id in overrides:
                raise ValidationError(
                    f"invalid season narrative relationship for {source_id}"
                )
            continue
        links.add((2017, source_id, relationship))
    unknown = set(overrides) - {source_id for _, source_id, _ in links}
    if unknown:
        raise ValidationError(f"season narrative overrides are unknown: {sorted(unknown)}")
    return sorted(links)


def derive_narrative_relationships(data: CorpusData) -> NarrativeRelationships:
    article_players, article_staff = _article_person_relationships(data)
    return NarrativeRelationships(
        article_games=tuple(_article_game_relationships(data)),
        article_players=tuple(article_players),
        article_staff=tuple(article_staff),
        play_by_play_players=tuple(_play_by_play_relationships(data)),
        group_sources=tuple(_group_source_relationships(data)),
        season_sources=tuple(_season_source_relationships(data)),
    )
