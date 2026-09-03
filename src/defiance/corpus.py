"""Offline assembly and validation of the preserved 2017 SDSU corpus."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3

from .corpus_db import CorpusData, load_corpus, validate_corpus_data, validate_database
from .corpus_inventory import decode_html, load_corpus_inventory, verify_inventory_raw
from .corpus_parse import (
    parse_article,
    parse_corpus_box_score,
    parse_roster,
    parse_season_statistics,
)
from .db import ValidationError


MANIFEST_PATH = Path("config/2017/corpus.json")
DATABASE_PATH = Path("data/normalized/2017.sqlite3")


@dataclass(frozen=True)
class CorpusSummary:
    discovered_sources: int
    available_in_scope_sources: int
    games: int
    series: int
    events: int
    schedule_group_memberships: int
    box_scores: int
    recap_sources: int
    play_by_play_games: int
    play_by_play_passages: int
    article_sources: int
    article_passages: int
    gaps: int
    conflicts: int


def _sources_by_id(manifest: dict[str, object]) -> dict[str, dict[str, object]]:
    sources = manifest["sources"]
    assert isinstance(sources, list)
    return {str(source["source_id"]): source for source in sources}


def _raw_source(
    repository_root: Path,
    sources: dict[str, dict[str, object]],
    source_id: str,
) -> bytes:
    source = sources.get(source_id)
    if source is None:
        raise ValidationError(f"inventory is missing source {source_id}")
    raw_path = source.get("raw_path")
    if not isinstance(raw_path, str):
        raise ValidationError(f"source {source_id} has no preserved raw path")
    return (repository_root / raw_path).read_bytes()


def _validate_record_conflicts(
    repository_root: Path,
    sources: dict[str, dict[str, object]],
    season_records: dict[str, str],
) -> None:
    schedule = decode_html(_raw_source(repository_root, sources, "sdsu-2017-schedule"))
    ncaa_central = decode_html(
        _raw_source(repository_root, sources, "sdsu-2017-ncaa-central")
    )
    schedule_values = {
        label: value
        for label, value in re.findall(
            r"schedule-stats-item__label[^>]*>\s*([^<]+)</strong>"
            r"\s*<strong[^>]*schedule-stats-item__value[^>]*>\s*([^<]+)",
            schedule,
        )
    }
    if schedule_values.get("Home") != "19-12":
        raise ValidationError("reviewed schedule home-record conflict is no longer present")
    if schedule_values.get("Away") != "19-8":
        raise ValidationError("reviewed schedule away-record conflict is no longer present")
    if season_records.get("Home games") != "19-11":
        raise ValidationError("final statistics home record is not 19-11")
    if season_records.get("Away games") != "19-9":
        raise ValidationError("final statistics away record is not 19-9")
    if season_records.get("Conference") != "20-10":
        raise ValidationError("final statistics conference record is not 20-10")
    if not re.search(
        r"San Diego State Aztecs\s+42-21\s*\(21-10(?:\s|<br\s*/?>)*Mountain West\)",
        ncaa_central,
        flags=re.IGNORECASE,
    ):
        raise ValidationError(
            "reviewed NCAA Central conference-record conflict is no longer present"
        )


def assemble_corpus(repository_root: Path) -> CorpusData:
    manifest = load_corpus_inventory(repository_root / MANIFEST_PATH)
    verify_inventory_raw(repository_root, manifest)
    sources = _sources_by_id(manifest)

    players, staff = parse_roster(
        _raw_source(repository_root, sources, "sdsu-2017-roster")
    )
    season_statistics = parse_season_statistics(
        _raw_source(repository_root, sources, "sdsu-2017-season-statistics")
    )

    games = manifest["games"]
    assert isinstance(games, list)
    box_scores = {}
    for game in games:
        source_id = game["box_score_source_id"]
        if not source_id:
            continue
        game_id = str(game["game_id"])
        box_scores[game_id] = parse_corpus_box_score(
            _raw_source(repository_root, sources, str(source_id)),
            game_id=game_id,
            opponent=str(game["opponent"]),
        )

    article_source_ids = {
        str(source["source_id"])
        for source in sources.values()
        if source["in_scope"]
        and source["status"] == "available"
        and source["kind"] in {"recap", "news_article", "postseason_hub"}
    }
    articles = {
        source_id: parse_article(_raw_source(repository_root, sources, source_id))
        for source_id in sorted(article_source_ids)
    }

    final_records = {
        record.label: f"{record.wins}-{record.losses}"
        for record in season_statistics.records
    }
    _validate_record_conflicts(repository_root, sources, final_records)

    data = CorpusData(
        manifest=manifest,
        players=players,
        staff=staff,
        season_statistics=season_statistics,
        box_scores=box_scores,
        articles=articles,
    )
    validate_corpus_data(data)
    return data


def corpus_summary(data: CorpusData) -> CorpusSummary:
    sources = data.manifest["sources"]
    gaps = data.manifest["known_gaps"]
    conflicts = data.manifest["known_conflicts"]
    schedule_groups = data.manifest["schedule_groups"]
    assert isinstance(sources, list)
    assert isinstance(gaps, list)
    assert isinstance(conflicts, list)
    assert isinstance(schedule_groups, list)
    return CorpusSummary(
        discovered_sources=len(sources),
        available_in_scope_sources=sum(
            source["in_scope"] and source["status"] == "available"
            for source in sources
        ),
        games=len(data.manifest["games"]),
        series=sum(group["group_type"] == "series" for group in schedule_groups),
        events=sum(group["group_type"] == "event" for group in schedule_groups),
        schedule_group_memberships=sum(
            len(group["members"]) for group in schedule_groups
        ),
        box_scores=len(data.box_scores),
        recap_sources=sum(
            source["kind"] == "recap" and source["status"] == "available"
            for source in sources
        ),
        play_by_play_games=sum(bool(box.play_by_play) for box in data.box_scores.values()),
        play_by_play_passages=sum(
            len(box.play_by_play) for box in data.box_scores.values()
        ),
        article_sources=len(data.articles),
        article_passages=sum(len(passages) for passages in data.articles.values()),
        gaps=len(gaps),
        conflicts=len(conflicts),
    )


def build_corpus(
    repository_root: Path,
    database_path: Path | None = None,
) -> CorpusSummary:
    data = assemble_corpus(repository_root)
    output_path = database_path or repository_root / DATABASE_PATH
    load_corpus(output_path, data)
    return corpus_summary(data)


def validate_existing_corpus(
    repository_root: Path,
    database_path: Path | None = None,
) -> CorpusSummary:
    data = assemble_corpus(repository_root)
    output_path = database_path or repository_root / DATABASE_PATH
    try:
        connection = sqlite3.connect(f"file:{output_path}?mode=ro", uri=True)
    except sqlite3.OperationalError as exc:
        raise ValidationError(f"cannot open normalized corpus {output_path}: {exc}") from exc
    try:
        validate_database(connection)
    finally:
        connection.close()
    return corpus_summary(data)
