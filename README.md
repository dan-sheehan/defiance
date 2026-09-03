# Defiance

Defiance V1 is a source-backed historical system for the 2017 San Diego State
baseball season. V1 is limited to material archived on the SDSU website.

The data path is deterministic:

```text
SDSU sources → preserved bytes → normalized rows → validation → SQLite
```

## 2017 corpus

The reviewed inventory is committed at `config/2017/corpus.json`. It records the
original URL, inclusion decision, SHA-256, local raw path, game relationships,
known gaps, and reviewed source conflicts. The current inventory contains:

- 248 discovered source entries: 225 available and in scope, 22 explicitly
  excluded, and one unavailable;
- all 63 scheduled games, 14 explicitly reviewed series, three tournament
  events, 51 ordered group memberships, and the 33-player, seven-member staff
  roster;
- complete overall and conference season batting, pitching, and fielding tables;
- 60 available game box scores and recap coverage for every game, including
  shared doubleheader recaps;
- 770 ordered play-by-play passages from the 43 games whose box reports contain
  play-by-play;
- 1,758 ordered passages from 151 included game, series, postseason, and season
  honor source entries.

The normalized database is generated at `data/normalized/2017.sqlite3`. Every
factual row carries a source ID and source locator. Play-by-play is preserved at
the source's half-inning narrative granularity; no plate-appearance fields are
inferred from prose.

Series and event membership is explicit rather than inferred at query time.
Separate home and road series against the same opponent have distinct IDs, and
each group plus each ordered game membership retains SDSU provenance. Group
records are derived and validated from the canonical game scores. Tournament
meetings are event members and are not relabeled as regular series.

Narrative relationships are built deterministically from the preserved article
blocks. `config/2017/narrative.json` records the reviewed passage assignments for
the three shared recaps plus explicit tournament and season-source exceptions.
Direct series-source relationships are created only when the reviewed series
provenance resolves to an exact preserved article passage; otherwise series
retrieval uses its member games. Exact full names and conservative source-scoped
surnames link article passages to rostered players, while staff links require an
exact full name. Play-by-play stays in a separate table and search index.

SQLite FTS5 indexes the 1,536 article heading/narrative blocks and all 770
play-by-play passages. The retrieval functions in `defiance.query` require at
least one exact structured selector (game, player, staff, opponent, group, or
season, as applicable) before optional literal lexical terms are applied. They
do not accept raw FTS syntax, fuzzy names, or unconstrained corpus-wide search.

## Commands

The repository uses Python 3.12 and [`uv`](https://docs.astral.sh/uv/). Use the
source tree directly:

```bash
PYTHONPATH=src uv run --no-sync python -m defiance.cli inventory-corpus
PYTHONPATH=src uv run --no-sync python -m defiance.cli build-corpus
PYTHONPATH=src uv run --no-sync python -m defiance.cli validate-corpus
PYTHONPATH=src uv run --no-sync python -m defiance.cli show-game 2017-04-15-unlv
PYTHONPATH=src uv run --no-sync python -m unittest discover -s tests -v
```

`inventory-corpus` contacts the SDSU archive, rechecks the reviewed discovery
boundary, and preserves source bytes. `build-corpus` and `validate-corpus` are
offline: they verify every available in-scope raw file against its inventory
hash before parsing or querying the database.

Downloaded documents and generated SQLite databases stay out of Git. The test
suite uses small committed source-format fixtures for roster, schedule, season
batting, season pitching, team facts, box scores, and recaps. Those parser and
grouping tests run offline in a clean checkout; the exhaustive full-corpus
integration test runs when the preserved local corpus is present and otherwise
skips.

`show-game` reads the completed corpus database. The original one-game builder
remains available separately, and its game is also present in the full corpus:

```bash
PYTHONPATH=src uv run --no-sync python -m defiance.cli build-slice
PYTHONPATH=src uv run --no-sync python -m defiance.cli show-game 2017-02-17-pacific
```

## Known archive gaps and conflicts

SDSU has no archived box-score link for the May 20 Fresno State game, the May 28
Fresno State Mountain West final, or the June 2 Long Beach State NCAA Regional
game. Seventeen other available box reports omit their `GAME.PLY` section, so
play-by-play is unavailable for 20 games in total. The SDSU PDF link for final
season statistics returns 404; the complete SDSU HTML statistics remain
available and are ingested.

Five contradictions are retained in both the inventory and database:

- April 13 at UNLV: schedule 3–6, box score 3–7;
- April 25 vs. UC Riverside: schedule 4–6, box score 4–7;
- home record: schedule 19–12, final statistics 19–11;
- away record: schedule 19–8, final statistics 19–9;
- conference record: SDSU's NCAA Central page 21–10, final statistics 20–10.

The contemporaneous box scores control the two game scores, and the final
season-statistics page controls the record summaries. These resolutions follow
the PRD's source-authority order while preserving both reported values. Optional
game statistics absent from a source are stored as `NULL`; zero is used only
when the source explicitly supplies that category.

Defiance-authored code is covered by this repository's MIT license. SDSU source
material remains the property of its original publisher and is preserved only
as local evidence or small test fixtures.
