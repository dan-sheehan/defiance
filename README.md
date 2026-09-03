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

## Deterministic questions and answers

`defiance.answer.answer_question(database_path, question)` is the single
product-level question-answer boundary. It resolves committed exact aliases,
routes bounded question patterns, and uses only fixed parameterized queries or
the selector-constrained narrative retrieval layer. Metric and query columns
are selected from code-owned whitelists; user text is never treated as SQL or
FTS syntax. Each call is independent and has no conversation memory.

The supported V1 patterns cover season, single-game, opponent, and series
player statistics; hitter best series; team leaders and record splits; game,
series, and tournament results; and scoped game, series, tournament, player,
and staff narrative questions. Entering an exact rostered full name returns up
to five deterministic, source-backed quick hitters; sparse records return fewer
rather than filler. Staff results label season and postseason facts as 2017 team
context unless an SDSU source explicitly attributes an accomplishment to that
person. Results contain source URLs and locators. An
unknown or ambiguous entity, incomplete aggregate, unsupported question, or
narrative question without a supporting passage returns an explicit failure
state instead of a guessed or partial answer. There is no fuzzy matching, model
provider, generated SQL, embedding index, or conversational fallback.

## Mobile web application

The Flask application in `defiance.web` is a thin WSGI interface over
`answer_question(database_path, question)`. It provides `GET /`, JSON
`POST /api/ask`, and `GET /healthz`. The browser uses small packaged CSS and
vanilla JavaScript assets with no frontend build step. Each accepted request is
independent; the application has no login, cookies, conversation transcript, or
cross-request user identity.

By default the server reads `data/normalized/2017.sqlite3` and writes anonymous
request audits to `data/runtime/audit.sqlite3`. Override those paths with
`DEFIANCE_CORPUS_DATABASE` and `DEFIANCE_AUDIT_DATABASE`. They must resolve to
different files. The corpus is opened read-only throughout the answer and
health paths; only the runtime audit database is writable.

Run the local development server after building the validated corpus:

```bash
PYTHONPATH=src uv run --no-sync flask --app 'defiance.web:create_app()' run
```

`POST /api/ask` accepts exactly one JSON string field named `question`. Engine
statuses remain HTTP 200 results with `request_id`, `status`, exact `text`,
public evidence links, and validated suggestions. Transport validation and
service failures use explicit 4xx or 5xx error objects. Public evidence contains
only its display label and approved original SDSU HTTPS URL; source IDs,
locators, raw paths, failure internals, and database paths remain server-side.

For each accepted request, the separate audit database records a random request
ID, UTC timestamp, exact submitted question, engine status and intent, exact
answer text, failure reason when applicable, elapsed processing time, and the
stable evidence source IDs, locators, and original SDSU URLs. It does not record
accounts, IP addresses, user agents, cookies, conversational state, or any other
cross-request identity.

## Commands

The repository uses Python 3.12 and [`uv`](https://docs.astral.sh/uv/). Use the
source tree directly:

```bash
PYTHONPATH=src uv run --no-sync python -m defiance.cli inventory-corpus
PYTHONPATH=src uv run --no-sync python -m defiance.cli build-corpus
PYTHONPATH=src uv run --no-sync python -m defiance.cli validate-corpus
PYTHONPATH=src uv run --no-sync python -m defiance.cli show-game 2017-04-15-unlv
PYTHONPATH=src uv run --no-sync python -m defiance.cli ask "How many home runs did Danny Sheehan hit in 2017?"
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

`ask` reads the generated full-corpus database and prints a short answer first,
followed by compact source references and independently parseable suggestions
when useful. Routing failures are exposed by the returned `AnswerResult` for
offline evaluation; no private-testing threshold or automatic model-provider
trigger is encoded in the application.

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
