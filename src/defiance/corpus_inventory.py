"""Source-specific discovery and preservation for the 2017 SDSU corpus."""

from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime
import gzip
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from typing import Iterable
from urllib.parse import urljoin, urlparse
from urllib.request import Request

from .fetch import SourceConfig, SourceError, _read_response, sha256_bytes


SCHEDULE_URL = "https://goaztecs.com/sports/baseball/schedule/season/2017"
ROSTER_URL = "https://goaztecs.com/sports/baseball/roster/season/2017"
SEASON_STATS_URL = (
    "https://goaztecs.com/news/2018/07/13/2017-baseball-html-statistics"
)
SEASON_STATS_PDF_URL = (
    "https://goaztecs.com/documents/2022/6/8/SDSU_BSB_Stats_Final_2017.pdf"
)
NCAA_CENTRAL_URL = "https://goaztecs.com/news/2018/07/13/2017-ncaa-central"
NEWS_ARCHIVE_URL = "https://goaztecs.com/sports/baseball/news/year/2017"
LEGACY_STATS_PATH = (
    "sandiegost_ftp.sidearmsports.com/custompages/sports/m-basebl/stats/"
)
USER_AGENT = "Defiance/0.1 source preservation"
KNOWN_CONFLICTS = [
    {
        "game_id": "2017-04-13-unlv",
        "field": "final_score",
        "source_a_id": "sdsu-2017-schedule",
        "source_a_value": "3-6",
        "source_a_locator": "schedule/event[35]",
        "source_b_id": "sdsu-2017-04-13-unlv-box-score",
        "source_b_value": "3-7",
        "source_b_locator": "GAME.NCA/team score headings",
        "resolution": (
            "Use the contemporaneous box score under the PRD source-authority order; "
            "retain the schedule value as an explicit conflict."
        ),
    },
    {
        "game_id": "2017-04-25-uc-riverside",
        "field": "final_score",
        "source_a_id": "sdsu-2017-schedule",
        "source_a_value": "4-6",
        "source_a_locator": "schedule/event[42]",
        "source_b_id": "sdsu-2017-04-25-uc-riverside-box-score",
        "source_b_value": "4-7",
        "source_b_locator": "GAME.NCA/team score headings",
        "resolution": (
            "Use the contemporaneous box score under the PRD source-authority order; "
            "retain the schedule value as an explicit conflict."
        ),
    },
    {
        "game_id": None,
        "field": "home_record",
        "source_a_id": "sdsu-2017-schedule",
        "source_a_value": "19-12",
        "source_a_locator": "schedule/summary/Home",
        "source_b_id": "sdsu-2017-season-statistics",
        "source_b_value": "19-11",
        "source_b_locator": "statistics/table[9]/row[4]",
        "resolution": (
            "Use the final season-statistics record summary; retain the schedule "
            "summary as an explicit conflict."
        ),
    },
    {
        "game_id": None,
        "field": "away_record",
        "source_a_id": "sdsu-2017-schedule",
        "source_a_value": "19-8",
        "source_a_locator": "schedule/summary/Away",
        "source_b_id": "sdsu-2017-season-statistics",
        "source_b_value": "19-9",
        "source_b_locator": "statistics/table[9]/row[5]",
        "resolution": (
            "Use the final season-statistics record summary; retain the schedule "
            "summary as an explicit conflict."
        ),
    },
    {
        "game_id": None,
        "field": "conference_record",
        "source_a_id": "sdsu-2017-ncaa-central",
        "source_a_value": "21-10",
        "source_a_locator": "embed-html/block[8]",
        "source_b_id": "sdsu-2017-season-statistics",
        "source_b_value": "20-10",
        "source_b_locator": "statistics/table[9]/row[2]",
        "resolution": (
            "Use the final season-statistics record summary; retain the postseason "
            "hub value as an explicit conflict."
        ),
    },
]

REVIEWED_SCHEDULE_GROUPS = (
    {
        "group_id": "series-2017-pacific-home",
        "group_type": "series",
        "label": "Pacific home series",
        "opponent": "Pacific",
        "source_id": "sdsu-2017-news-2017-02-19-aztec-capture-series-with-shutout-win-over-pacific",
        "source_locator": "embed-html/block[3]",
        "game_ids": (
            "2017-02-17-pacific",
            "2017-02-18-pacific",
            "2017-02-19-pacific",
        ),
    },
    {
        "group_id": "series-2017-cal-poly-home",
        "group_type": "series",
        "label": "Cal Poly home series",
        "opponent": "Cal Poly",
        "source_id": "sdsu-2017-news-2017-03-01-aztecs-host-cal-poly-for-three-game-series",
        "source_locator": "embed-html/block[3]",
        "game_ids": (
            "2017-03-03-cal-poly",
            "2017-03-04-cal-poly",
            "2017-03-05-cal-poly",
        ),
    },
    {
        "group_id": "series-2017-nevada-away",
        "group_type": "series",
        "label": "Nevada road series",
        "opponent": "Nevada",
        "source_id": "sdsu-2017-news-2017-03-10-aztecs-open-series-at-nevada-this-afternoon",
        "source_locator": "embed-html/block[2]",
        "game_ids": (
            "2017-03-10-nevada",
            "2017-03-11-nevada",
            "2017-03-12-nevada",
        ),
    },
    {
        "group_id": "series-2017-unlv-home",
        "group_type": "series",
        "label": "UNLV home series",
        "opponent": "UNLV",
        "source_id": "sdsu-2017-news-2017-03-15-aztecs-open-conference-home-play-with-series-vs-unlv",
        "source_locator": "embed-html/block[3]",
        "game_ids": (
            "2017-03-17-unlv",
            "2017-03-18-unlv",
            "2017-03-19-unlv",
        ),
    },
    {
        "group_id": "series-2017-fresno-state-away",
        "group_type": "series",
        "label": "Fresno State road series",
        "opponent": "Fresno State",
        "source_id": "sdsu-2017-news-2017-03-22-aztecs-visit-fresno-state-for-three-game-mw-series",
        "source_locator": "embed-html/block[3]",
        "game_ids": (
            "2017-03-25-fresno-state-1",
            "2017-03-25-fresno-state-2",
            "2017-03-26-fresno-state",
        ),
    },
    {
        "group_id": "series-2017-san-jose-state-home",
        "group_type": "series",
        "label": "San Jose State home series",
        "opponent": "San Jose State",
        "source_id": "sdsu-2017-news-2017-03-29-aztecs-host-mw-series-vs-san-jose-state",
        "source_locator": "embed-html/block[3]",
        "game_ids": (
            "2017-03-31-san-jose-state",
            "2017-04-01-san-jose-state",
            "2017-04-02-san-jose-state",
        ),
    },
    {
        "group_id": "series-2017-nevada-home",
        "group_type": "series",
        "label": "Nevada home series",
        "opponent": "Nevada",
        "source_id": "sdsu-2017-news-2017-04-06-aztecs-set-to-host-nevada-for-three-game-conference-series",
        "source_locator": "embed-html/block[3]",
        "game_ids": (
            "2017-04-07-nevada",
            "2017-04-08-nevada",
            "2017-04-09-nevada",
        ),
    },
    {
        "group_id": "series-2017-unlv-away",
        "group_type": "series",
        "label": "UNLV road series",
        "opponent": "UNLV",
        "source_id": "sdsu-2017-news-2017-04-12-aztecs-travel-to-las-vegas-for-mw-baseball-series",
        "source_locator": "embed-html/block[3]",
        "game_ids": (
            "2017-04-13-unlv",
            "2017-04-14-unlv",
            "2017-04-15-unlv",
        ),
    },
    {
        "group_id": "series-2017-uc-santa-barbara-away",
        "group_type": "series",
        "label": "UC Santa Barbara road series",
        "opponent": "UC Santa Barbara",
        "source_id": "sdsu-2017-news-2017-04-21-aztecs-open-three-game-series-at-uc-santa-barbara-this-afternoon",
        "source_locator": "embed-html/block[2]",
        "game_ids": (
            "2017-04-21-uc-santa-barbara",
            "2017-04-22-uc-santa-barbara",
            "2017-04-23-uc-santa-barbara",
        ),
    },
    {
        "group_id": "series-2017-new-mexico-home",
        "group_type": "series",
        "label": "New Mexico home series",
        "opponent": "New Mexico",
        "source_id": "sdsu-2017-news-2017-04-27-aztecs-set-for-series-vsnew-mexico-this-weekend",
        "source_locator": "embed-html/block[3]",
        "game_ids": (
            "2017-04-28-new-mexico",
            "2017-04-29-new-mexico",
            "2017-04-30-new-mexico",
        ),
    },
    {
        "group_id": "series-2017-san-jose-state-away",
        "group_type": "series",
        "label": "San Jose State road series",
        "opponent": "San Jose State",
        "source_id": "sdsu-2017-news-2017-05-03-aztecs-visit-san-jose-state-for-three-game-baseball-series",
        "source_locator": "embed-html/block[3]",
        "game_ids": (
            "2017-05-05-san-jose-state",
            "2017-05-06-san-jose-state",
            "2017-05-07-san-jose-state",
        ),
    },
    {
        "group_id": "series-2017-air-force-away",
        "group_type": "series",
        "label": "Air Force road series",
        "opponent": "Air Force",
        "source_id": "sdsu-2017-news-2017-05-10-aztecs-visit-air-force-for-mw-baseball-series",
        "source_locator": "embed-html/block[3]",
        "game_ids": (
            "2017-05-12-air-force",
            "2017-05-13-air-force",
            "2017-05-14-air-force",
        ),
    },
    {
        "group_id": "series-2017-san-diego-season",
        "group_type": "series",
        "label": "San Diego season series",
        "opponent": "San Diego",
        "source_id": "sdsu-2017-news-2017-05-16-aztec-down-toreros-9-5-to-win-season-series",
        "source_locator": "embed-html/block[3]",
        "game_ids": (
            "2017-03-14-san-diego",
            "2017-05-16-san-diego",
        ),
    },
    {
        "group_id": "series-2017-fresno-state-home",
        "group_type": "series",
        "label": "Fresno State home series",
        "opponent": "Fresno State",
        "source_id": "sdsu-2017-news-2017-05-17-aztecs-host-fresno-state-for-final-regular-season-series",
        "source_locator": "embed-html/block[3]",
        "game_ids": (
            "2017-05-18-fresno-state",
            "2017-05-19-fresno-state",
            "2017-05-20-fresno-state",
        ),
    },
    {
        "group_id": "event-2017-tony-gwynn-legacy",
        "group_type": "event",
        "label": "Tony Gwynn Legacy",
        "opponent": None,
        "source_id": "sdsu-2017-schedule",
        "source_locator": "schedule/tournament[Tony Gwynn Legacy]",
        "game_ids": (
            "2017-02-24-tennessee",
            "2017-02-25-seton-hall",
            "2017-02-25-notre-dame",
        ),
    },
    {
        "group_id": "event-2017-mountain-west-tournament",
        "group_type": "event",
        "label": "Mountain West Tournament",
        "opponent": None,
        "source_id": "sdsu-2017-schedule",
        "source_locator": "schedule/tournament[Mountain West Tournament]",
        "game_ids": (
            "2017-05-25-fresno-state",
            "2017-05-26-new-mexico",
            "2017-05-27-fresno-state",
            "2017-05-28-fresno-state",
        ),
    },
    {
        "group_id": "event-2017-ncaa-tournament",
        "group_type": "event",
        "label": "NCAA Tournament",
        "opponent": None,
        "source_id": "sdsu-2017-schedule",
        "source_locator": "schedule/tournament[NCAA Tournament]",
        "game_ids": (
            "2017-06-02-long-beach-state",
            "2017-06-03-ucla",
            "2017-06-04-long-beach-state",
        ),
    },
)


@dataclass(frozen=True)
class ScheduleEvent:
    schedule_order: int
    display_date: str
    opponent: str
    designation: str
    result: str
    location: str
    tournament: str | None
    stats_url: str | None
    recap_url: str | None


@dataclass(frozen=True)
class ArticleLink:
    title: str
    url: str


def _clean(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def decode_html(content: bytes) -> str:
    decoded = gzip.decompress(content) if content.startswith(b"\x1f\x8b") else content
    return decoded.decode("utf-8")


def canonical_url(url: str) -> str:
    if url.startswith("http://"):
        return "https://" + url.removeprefix("http://")
    return url


class _ScheduleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.events: list[dict[str, object]] = []
        self.event: dict[str, object] | None = None
        self.event_depth = 0
        self.capture: dict[str, object] | None = None
        self.current_tournament: str | None = None
        self.tournament_capture: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        exact_class = attributes.get("class")

        if tag == "div" and "schedule-events-by-tournament" in classes:
            self.current_tournament = None
        if tag == "strong" and "schedule-events-by-tournament__title" in classes:
            self.tournament_capture = []

        if (
            tag == "div"
            and exact_class in {"schedule-event", "schedule-event item"}
            and self.event is None
        ):
            self.event = {
                "date": "",
                "team": "",
                "result": "",
                "location": "",
                "links": [],
                "tournament": self.current_tournament,
            }
            self.event_depth = 1
            return

        if self.event is None:
            return
        if tag == "div":
            self.event_depth += 1

        kind: str | None = None
        if tag == "time" and not self.event["date"]:
            kind = "date"
        elif tag == "strong" and "schedule-event-default-team__name" in classes:
            kind = "team"
        elif (
            tag == "div"
            and "schedule-event-item-result__label" in classes
            and not self.event["result"]
        ):
            kind = "result"
        elif tag == "span" and "schedule-event-location" in classes:
            kind = "location"
        if kind is not None:
            self.capture = {"kind": kind, "tag": tag, "depth": 1, "text": []}
        elif self.capture is not None:
            self.capture["depth"] = int(self.capture["depth"]) + 1

        if tag == "a" and attributes.get("href"):
            links = self.event["links"]
            assert isinstance(links, list)
            links.append(
                (
                    canonical_url(urljoin(SCHEDULE_URL, attributes["href"])),
                    attributes.get("aria-label") or "",
                )
            )

    def handle_data(self, data: str) -> None:
        if self.tournament_capture is not None:
            self.tournament_capture.append(data)
        if self.capture is not None:
            text = self.capture["text"]
            assert isinstance(text, list)
            text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "strong" and self.tournament_capture is not None:
            self.current_tournament = _clean("".join(self.tournament_capture)) or None
            self.tournament_capture = None

        if self.event is None:
            return
        if self.capture is not None:
            self.capture["depth"] = int(self.capture["depth"]) - 1
            if self.capture["depth"] == 0:
                text = self.capture["text"]
                assert isinstance(text, list)
                self.event[str(self.capture["kind"])] = _clean("".join(text))
                self.capture = None

        if tag == "div":
            self.event_depth -= 1
            if self.event_depth == 0:
                self.events.append(self.event)
                self.event = None


def parse_schedule_events(
    content: bytes, *, expected_events: int = 63
) -> tuple[ScheduleEvent, ...]:
    parser = _ScheduleParser()
    parser.feed(decode_html(content))
    parser.close()
    events: list[ScheduleEvent] = []
    for order, raw in enumerate(parser.events, start=1):
        links = raw["links"]
        assert isinstance(links, list)
        stats_url = next((url for url, _ in links if LEGACY_STATS_PATH in url), None)
        recap_url = next((url for url, _ in links if "/news/2017/" in url), None)
        team = _clean(str(raw["team"]))
        designation = "at" if team.startswith("at ") else "vs"
        opponent = re.sub(r"^(?:at|vs\.)\s+", "", team).strip()
        if not opponent:
            raise SourceError(f"schedule event {order} is missing an opponent")
        events.append(
            ScheduleEvent(
                schedule_order=order,
                display_date=str(raw["date"]),
                opponent=opponent,
                designation=designation,
                result=_clean(str(raw["result"])),
                location=_clean(str(raw["location"])),
                tournament=str(raw["tournament"]) if raw["tournament"] else None,
                stats_url=stats_url,
                recap_url=recap_url,
            )
        )
    if len(events) != expected_events:
        raise SourceError(
            f"expected {expected_events} schedule events, discovered {len(events)}"
        )
    return tuple(events)


class _AnchorParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.href: str | None = None
        self.text: list[str] = []
        self.anchors: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self.href = dict(attrs).get("href")
            self.text = []

    def handle_data(self, data: str) -> None:
        if self.href is not None:
            self.text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.href is not None:
            self.anchors.append(
                (
                    _clean("".join(self.text)),
                    canonical_url(urljoin(self.base_url, self.href)),
                )
            )
            self.href = None
            self.text = []


def parse_news_archive(content: bytes, base_url: str) -> tuple[ArticleLink, ...]:
    parser = _AnchorParser(base_url)
    parser.feed(decode_html(content))
    parser.close()
    by_url: dict[str, ArticleLink] = {}
    for title, url in parser.anchors:
        if "/news/2017/" in url and title:
            by_url.setdefault(url, ArticleLink(title=title, url=url))
    return tuple(by_url.values())


def _fetch(url: str, kind: str = "html") -> bytes:
    config_kind = "box_score" if LEGACY_STATS_PATH in url else kind
    config = SourceConfig("discovery", config_kind, url, "0" * 64)
    request = Request(url, headers={"User-Agent": USER_AGENT})
    return _read_response(config, request, 30.0)


def _extension(url: str) -> str:
    suffix = Path(urlparse(url).path).suffix.casefold()
    return suffix if suffix in {".html", ".htm", ".pdf", ".xml"} else ".html"


def _preserve(
    source_id: str,
    url: str,
    content: bytes,
    raw_dir: Path,
    repository_root: Path,
) -> tuple[str, str]:
    digest = sha256_bytes(content)
    filename = f"{source_id}__{digest}{_extension(url)}"
    destination = raw_dir / filename
    raw_dir.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.read_bytes() != content:
            raise SourceError(f"refusing to overwrite changed raw source: {destination}")
    else:
        with destination.open("xb") as handle:
            handle.write(content)
    return digest, str(destination.relative_to(repository_root))


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def canonical_opponent(value: str) -> str:
    """Remove schedule-only rankings and tournament seeds from an opponent."""

    result = re.sub(r"^No\.\s+\d+(?:/\d+)?\s+", "", value).strip()
    result = re.sub(r"^\(\d+\)\s+", "", result).strip()
    return result


def _article_date(url: str) -> date:
    match = re.search(r"/news/2017/(\d{1,2})/(\d{1,2})/", url)
    if not match:
        raise SourceError(f"cannot parse article date: {url}")
    return date(2017, int(match.group(1)), int(match.group(2)))


def _article_source_id(url: str) -> str:
    article_date = _article_date(url)
    article_slug = url.rstrip("/").rsplit("/", 1)[-1]
    return f"sdsu-2017-news-{article_date.isoformat()}-{_slug(article_slug)}"


def _box_source_id(game_id: str) -> str:
    if game_id == "2017-02-17-pacific":
        return "sdsu-2017-02-17-pacific-box-score"
    return f"sdsu-{game_id}-box-score"


def _recap_source_id(url: str) -> str:
    if url.endswith("aztecs-win-halted-game-drop-nightcap-to-pacific"):
        return "sdsu-2017-02-17-pacific-recap"
    return _article_source_id(url)


def _classify_articles(
    articles: Iterable[ArticleLink], recap_urls: set[str]
) -> dict[str, tuple[bool, str, str | None]]:
    articles = tuple(articles)
    title_counts = Counter(article.title.casefold() for article in articles)
    canonical_for_title: dict[str, str] = {}
    for article in sorted(articles, key=lambda item: (item.url.endswith("-1"), item.url)):
        canonical_for_title.setdefault(article.title.casefold(), article.url)

    excluded_fragments = {
        "first-pitch-luncheon": "administrative event outside the played season",
        "adds-three-players-for-2018": "2018 recruiting material",
        "honor-first-responders": "event promotion without season facts",
        "fundraising-campaign": "fundraising material outside baseball facts",
        "mlb-draft": "professional draft material outside the SDSU season corpus",
        "summer-baseball": "postseason summer baseball outside the SDSU season",
    }
    classifications: dict[str, tuple[bool, str, str | None]] = {}
    for article in articles:
        url = article.url
        title_key = article.title.casefold()
        if url in recap_urls:
            classifications[url] = (True, "game_recap", None)
            continue
        if title_counts[title_key] > 1 and canonical_for_title[title_key] != url:
            classifications[url] = (
                False,
                "duplicate",
                f"duplicate archive entry for {canonical_for_title[title_key]}",
            )
            continue
        exclusion = next(
            (reason for fragment, reason in excluded_fragments.items() if fragment in url),
            None,
        )
        article_date = _article_date(url)
        if exclusion is not None:
            classifications[url] = (False, "excluded", exclusion)
        elif article_date > date(2017, 6, 19):
            classifications[url] = (
                False,
                "excluded",
                "published after the 2017 season and immediate season honors",
            )
        elif article_date < date(2017, 2, 8):
            classifications[url] = (
                False,
                "excluded",
                "published before official 2017 preseason coverage",
            )
        elif any(
            word in title_key
            for word in ("named", "award", "honor", "all-american", "watch list")
        ):
            classifications[url] = (True, "season_honor", None)
        else:
            classifications[url] = (True, "game_or_series_context", None)
    return classifications


def _game_ids(events: tuple[ScheduleEvent, ...]) -> list[str]:
    year = 2017
    dated: list[tuple[date, str]] = []
    for event in events:
        game_date = datetime.strptime(f"{event.display_date} {year}", "%b %d %Y").date()
        dated.append((game_date, _slug(canonical_opponent(event.opponent))))
    counts = Counter(dated)
    seen: Counter[tuple[date, str]] = Counter()
    result: list[str] = []
    for key in dated:
        seen[key] += 1
        base = f"{key[0].isoformat()}-{key[1]}"
        result.append(f"{base}-{seen[key]}" if counts[key] > 1 else base)
    return result


def _source_entry(
    source_id: str,
    kind: str,
    url: str,
    *,
    in_scope: bool,
    status: str,
    classification: str,
    title: str | None = None,
    sha256: str | None = None,
    raw_path: str | None = None,
    notes: str | None = None,
) -> dict[str, object]:
    return {
        "source_id": source_id,
        "kind": kind,
        "url": url,
        "in_scope": in_scope,
        "status": status,
        "classification": classification,
        "title": title,
        "sha256": sha256,
        "raw_path": raw_path,
        "notes": notes,
    }


def reviewed_schedule_groups(
    games: list[dict[str, object]],
) -> list[dict[str, object]]:
    schedule_order = {
        str(game["game_id"]): int(game["schedule_order"]) for game in games
    }
    groups: list[dict[str, object]] = []
    for reviewed in REVIEWED_SCHEDULE_GROUPS:
        members = []
        for group_order, game_id in enumerate(reviewed["game_ids"], start=1):
            game_id = str(game_id)
            members.append(
                {
                    "game_id": game_id,
                    "group_order": group_order,
                    "source_id": "sdsu-2017-schedule",
                    "source_locator": f"schedule/event[{schedule_order[game_id]}]",
                }
            )
        groups.append(
            {
                key: reviewed[key]
                for key in (
                    "group_id",
                    "group_type",
                    "label",
                    "opponent",
                    "source_id",
                    "source_locator",
                )
            }
            | {"members": members}
        )
    return groups


def create_corpus_inventory(repository_root: Path) -> dict[str, object]:
    """Discover, preserve, and write the reviewed 2017 corpus inventory."""

    raw_dir = repository_root / "data" / "raw"
    manifest_path = repository_root / "config" / "2017" / "corpus.json"

    canonical_urls = {
        "sdsu-2017-schedule": ("schedule", SCHEDULE_URL, "canonical_schedule"),
        "sdsu-2017-roster": ("roster", ROSTER_URL, "canonical_roster"),
        "sdsu-2017-season-statistics": (
            "season_statistics",
            SEASON_STATS_URL,
            "canonical_season_statistics",
        ),
        "sdsu-2017-ncaa-central": (
            "postseason_hub",
            NCAA_CENTRAL_URL,
            "postseason_context",
        ),
    }
    fetched: dict[str, bytes] = {}
    for source_id, (_, url, _) in canonical_urls.items():
        fetched[url] = _fetch(url)

    events = parse_schedule_events(fetched[SCHEDULE_URL])

    archive_pages: list[tuple[str, bytes]] = []
    all_articles: dict[str, ArticleLink] = {}
    for page_number in range(1, 100):
        url = NEWS_ARCHIVE_URL if page_number == 1 else f"{NEWS_ARCHIVE_URL}?page={page_number}"
        content = _fetch(url)
        page_articles = parse_news_archive(content, url)
        if not page_articles:
            break
        archive_pages.append((url, content))
        for article in page_articles:
            all_articles.setdefault(article.url, article)
    if len(archive_pages) != 11 or len(all_articles) != 172:
        raise SourceError(
            "unexpected news archive coverage: "
            f"pages={len(archive_pages)}, articles={len(all_articles)}"
        )

    recap_urls = {event.recap_url for event in events if event.recap_url}
    recap_urls.add(
        "https://goaztecs.com/news/2017/05/18/aztecs-drop-4-0-decision-to-fresno-state"
    )
    classifications = _classify_articles(all_articles.values(), recap_urls)

    sources: list[dict[str, object]] = []
    content_by_source: dict[str, bytes] = {}
    for source_id, (kind, url, classification) in canonical_urls.items():
        digest, raw_path = _preserve(
            source_id, url, fetched[url], raw_dir, repository_root
        )
        sources.append(
            _source_entry(
                source_id,
                kind,
                url,
                in_scope=True,
                status="available",
                classification=classification,
                sha256=digest,
                raw_path=raw_path,
            )
        )
        content_by_source[source_id] = fetched[url]

    for page_number, (url, content) in enumerate(archive_pages, start=1):
        source_id = f"sdsu-2017-news-archive-page-{page_number}"
        digest, raw_path = _preserve(source_id, url, content, raw_dir, repository_root)
        sources.append(
            _source_entry(
                source_id,
                "news_archive",
                url,
                in_scope=True,
                status="available",
                classification="discovery_evidence",
                sha256=digest,
                raw_path=raw_path,
            )
        )
        content_by_source[source_id] = content

    game_ids = _game_ids(events)
    box_source_by_url: dict[str, str] = {}
    for event, game_id in zip(events, game_ids, strict=True):
        if event.stats_url:
            box_source_by_url[event.stats_url] = _box_source_id(game_id)

    article_source_by_url: dict[str, str] = {}
    for article in all_articles.values():
        in_scope, classification, notes = classifications[article.url]
        source_id = (
            _recap_source_id(article.url)
            if article.url in recap_urls
            else _article_source_id(article.url)
        )
        article_source_by_url[article.url] = source_id
        sources.append(
            _source_entry(
                source_id,
                "recap" if article.url in recap_urls else "news_article",
                article.url,
                in_scope=in_scope,
                status="available" if in_scope else "excluded",
                classification=classification,
                title=article.title,
                notes=notes,
            )
        )

    for url, source_id in sorted(box_source_by_url.items()):
        sources.append(
            _source_entry(
                source_id,
                "box_score",
                url,
                in_scope=True,
                status="available",
                classification="game_statistics",
            )
        )

    sources.append(
        _source_entry(
            "sdsu-2017-season-statistics-pdf",
            "season_statistics_pdf",
            SEASON_STATS_PDF_URL,
            in_scope=True,
            status="unavailable",
            classification="canonical_season_statistics",
            notes="SDSU archive link returns HTTP 404 as of 2026-09-02",
        )
    )

    fetch_entries = [
        source
        for source in sources
        if source["in_scope"]
        and source["status"] == "available"
        and source["sha256"] is None
    ]
    print(f"Fetching {len(fetch_entries)} in-scope corpus sources...", flush=True)
    with ThreadPoolExecutor(max_workers=6) as executor:
        future_to_source = {
            executor.submit(_fetch, str(source["url"]), str(source["kind"])): source
            for source in fetch_entries
        }
        completed = 0
        for future in as_completed(future_to_source):
            source = future_to_source[future]
            content = future.result()
            digest, raw_path = _preserve(
                str(source["source_id"]),
                str(source["url"]),
                content,
                raw_dir,
                repository_root,
            )
            source["sha256"] = digest
            source["raw_path"] = raw_path
            content_by_source[str(source["source_id"])] = content
            completed += 1
            if completed % 20 == 0 or completed == len(fetch_entries):
                print(f"Preserved {completed}/{len(fetch_entries)}", flush=True)

    game_records: list[dict[str, object]] = []
    gaps: list[dict[str, object]] = []
    may_18_recap = (
        "https://goaztecs.com/news/2017/05/18/aztecs-drop-4-0-decision-to-fresno-state"
    )
    opening_recap = (
        "https://goaztecs.com/news/2017/02/18/"
        "aztecs-win-halted-game-drop-nightcap-to-pacific"
    )
    for event, game_id in zip(events, game_ids, strict=True):
        game_date = datetime.strptime(
            f"{event.display_date} 2017", "%b %d %Y"
        ).date()
        recap_url = event.recap_url
        if event.schedule_order == 1:
            recap_url = opening_recap
        elif event.schedule_order == 54:
            recap_url = may_18_recap
        box_source_id = (
            box_source_by_url[event.stats_url] if event.stats_url else None
        )
        recap_source_id = article_source_by_url[recap_url] if recap_url else None
        pbp_available = False
        if box_source_id:
            pbp_available = b'NAME="GAME.PLY"' in content_by_source[box_source_id].upper()
        if box_source_id is None:
            gaps.append(
                {
                    "game_id": game_id,
                    "kind": "box_score",
                    "reason": "no box-score/statistics link is archived by SDSU",
                }
            )
        if not pbp_available:
            gap = {
                "game_id": game_id,
                "kind": "play_by_play",
                "reason": (
                    "no box score is archived by SDSU"
                    if box_source_id is None
                    else "archived box score contains no GAME.PLY play-by-play section"
                ),
            }
            if box_source_id:
                gap["source_id"] = box_source_id
            gaps.append(gap)
        game_records.append(
            {
                "game_id": game_id,
                "schedule_order": event.schedule_order,
                "game_date": game_date.isoformat(),
                "opponent": canonical_opponent(event.opponent),
                "source_opponent": event.opponent,
                "designation": event.designation,
                "result": event.result,
                "location": event.location,
                "tournament": event.tournament,
                "schedule_source_id": "sdsu-2017-schedule",
                "box_score_source_id": box_source_id,
                "recap_source_id": recap_source_id,
                "play_by_play_available": pbp_available,
            }
        )

    gaps.append(
        {
            "source_id": "sdsu-2017-season-statistics-pdf",
            "kind": "source_unavailable",
            "reason": "the SDSU archive PDF link returns HTTP 404; HTML statistics remain available",
        }
    )

    source_ids = [str(source["source_id"]) for source in sources]
    if len(source_ids) != len(set(source_ids)):
        duplicates = [key for key, count in Counter(source_ids).items() if count > 1]
        raise SourceError(f"duplicate source IDs: {duplicates}")

    manifest: dict[str, object] = {
        "schema_version": 2,
        "season": 2017,
        "source_boundary": "San Diego State website only",
        "discovered_at": "2026-09-02",
        "sources": sorted(sources, key=lambda item: str(item["source_id"])),
        "games": game_records,
        "schedule_groups": reviewed_schedule_groups(game_records),
        "known_gaps": gaps,
        "known_conflicts": KNOWN_CONFLICTS,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    return manifest


def load_corpus_inventory(path: Path) -> dict[str, object]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SourceError(f"cannot read corpus inventory {path}: {exc}") from exc
    if manifest.get("schema_version") != 2 or manifest.get("season") != 2017:
        raise SourceError("unsupported corpus inventory schema or season")
    sources = manifest.get("sources")
    games = manifest.get("games")
    if not isinstance(sources, list) or not isinstance(games, list):
        raise SourceError("corpus inventory is missing sources or games")
    return manifest


def verify_inventory_raw(repository_root: Path, manifest: dict[str, object]) -> None:
    sources = manifest["sources"]
    assert isinstance(sources, list)
    for source in sources:
        assert isinstance(source, dict)
        if not source["in_scope"] or source["status"] != "available":
            continue
        raw_path = source.get("raw_path")
        expected_hash = source.get("sha256")
        if not isinstance(raw_path, str) or not isinstance(expected_hash, str):
            raise SourceError(f"source lacks raw provenance: {source['source_id']}")
        path = repository_root / raw_path
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise SourceError(f"missing raw source {source['source_id']}: {path}") from exc
        actual_hash = sha256_bytes(content)
        if actual_hash != expected_hash:
            raise SourceError(
                f"raw source hash mismatch for {source['source_id']}: "
                f"expected {expected_hash}, got {actual_hash}"
            )
