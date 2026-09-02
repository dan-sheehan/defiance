"""Command-line entry points for the Milestone 1 vertical slice."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .db import ValidationError, load_slice
from .fetch import SourceError, fetch_and_preserve, load_config, verify_preserved
from .parse import ParseError, parse_box_score, parse_recap
from .query import QueryError, show_game


REPOSITORY_ROOT = Path.cwd().resolve()
CONFIG_PATH = REPOSITORY_ROOT / "config" / "2017" / "one_game.json"
RAW_DIR = REPOSITORY_ROOT / "data" / "raw"
DATABASE_PATH = REPOSITORY_ROOT / "data" / "normalized" / "milestone1.sqlite3"


def build_slice() -> str:
    configs = load_config(CONFIG_PATH)
    preserved = tuple(fetch_and_preserve(source, RAW_DIR) for source in configs)
    source_by_kind = {source.config.kind: source for source in preserved}
    box = source_by_kind["box_score"]
    recap = source_by_kind["recap"]
    game = parse_box_score(verify_preserved(box.config, box.raw_path))
    passages = parse_recap(verify_preserved(recap.config, recap.raw_path))
    stored_paths = {
        source.config.source_id: str(source.raw_path.relative_to(REPOSITORY_ROOT))
        for source in preserved
    }
    load_slice(
        DATABASE_PATH,
        game,
        passages,
        preserved,
        stored_raw_paths=stored_paths,
    )
    return game.game_id


def _evidence(row: dict[str, object]) -> str:
    return (
        f"source={row['original_url']} | raw={row['raw_path']} | "
        f"locator={row['source_locator']}"
    )


def format_game(result: dict[str, object]) -> str:
    game = result["game"]
    assert isinstance(game, dict)
    lines = [
        f"Game: {game['game_date']} vs. {game['opponent']}",
        f"Final: San Diego State {game['sdsu_score']}, {game['opponent']} {game['opponent_score']}",
        f"Evidence: {_evidence(game)}",
        "",
        "SDSU batting",
    ]
    batting = result["batting"]
    assert isinstance(batting, list)
    for row in batting:
        lines.extend(
            (
                (
                    f"- {row['full_name']} ({row['position']}): "
                    f"AB {row['ab']}, R {row['r']}, H {row['h']}, RBI {row['rbi']}, "
                    f"BB {row['bb']}, SO {row['so']}, PO {row['po']}, A {row['a']}, LOB {row['lob']}; "
                    f"2B {row['doubles']}, 3B {row['triples']}, HR {row['home_runs']}, "
                    f"HBP {row['hit_by_pitch']}, SH {row['sacrifice_hits']}, "
                    f"SF {row['sacrifice_flies']}, SB {row['stolen_bases']}, "
                    f"CS {row['caught_stealing']}, E {row['errors']}"
                ),
                f"  {_evidence(row)}",
            )
        )

    lines.extend(("", "SDSU pitching"))
    pitching = result["pitching"]
    assert isinstance(pitching, list)
    for row in pitching:
        innings = f"{row['outs'] // 3}.{row['outs'] % 3}"
        decision = f" {row['decision']}" if row["decision"] else ""
        lines.extend(
            (
                (
                    f"- {row['full_name']}{decision}: IP {innings}, H {row['h']}, "
                    f"R {row['r']}, ER {row['er']}, BB {row['bb']}, SO {row['so']}, "
                    f"WP {row['wp']}, BK {row['bk']}, HBP {row['hbp']}, IBB {row['ibb']}, "
                    f"AB {row['ab']}, BF {row['bf']}, FO {row['fo']}, GO {row['go']}, NP {row['np']}"
                ),
                f"  {_evidence(row)}",
            )
        )

    lines.extend(("", "Recap"))
    passages = result["recap_passages"]
    assert isinstance(passages, list)
    for row in passages:
        lines.extend((f"{row['passage_order']}. {row['text']}", f"   {_evidence(row)}"))
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="defiance")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("build-slice", help="fetch, validate, and load Milestone 1")
    show = subcommands.add_parser("show-game", help="show one normalized game")
    show.add_argument("game_id")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "build-slice":
            game_id = build_slice()
            print(f"Built Milestone 1 game: {game_id}")
            print(f"Database: {DATABASE_PATH}")
        else:
            print(format_game(show_game(DATABASE_PATH, arguments.game_id)))
    except (ParseError, QueryError, SourceError, ValidationError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
