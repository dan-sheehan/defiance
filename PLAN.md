# Defiance V1 — Minimal Foundation and Milestone 1

## Minimal Repository Foundation

Create only what is necessary to make the public repository understandable and begin the vertical slice:

```text
defiance/
├── README.md
├── PRD.md
├── AGENTS.md
├── LICENSE
├── .gitignore
├── pyproject.toml
├── uv.lock
├── config/
│   └── 2017/
├── src/
│   └── defiance/
├── tests/
│   └── fixtures/
└── data/
    ├── raw/
    └── normalized/
```

Foundation contents:

- Commit `PRD.md` unchanged as the product authority.
- Add the repository’s `AGENTS.md`.
- Add a concise README containing:
  - what Defiance V1 is;
  - the 2017/SDSU-only boundary;
  - the source-to-query pipeline;
  - local commands once they exist;
  - the distinction between Defiance code and SDSU source material.
- Add an MIT license covering only Defiance-authored code.
- Add `.gitignore` rules for:
  - full raw source files;
  - generated SQLite databases;
  - virtual environments, caches, logs, coverage, and secrets.
- Add a minimal `pyproject.toml` using Python 3.12 and `uv`.
- Generate `uv.lock` only after the first real source format determines whether a parsing dependency is needed.

Defer until Milestone 1 produces code or tests that need them:

- CI configuration;
- separate architecture documentation;
- formatting or lint dependencies;
- contribution templates;
- deployment configuration;
- source inventories beyond the selected game.

Suggested foundation commit:

`chore: establish Defiance V1 repository foundation`

## Milestone 1 — One Real Game from Source to Query

### Objective

Prove the smallest complete path:

```text
real SDSU source
→ preserved raw bytes
→ source-specific parsing
→ normalized rows
→ explicit validation
→ SQLite
→ deterministic query
→ original-source provenance
```

### Source selection

Inspect the real SDSU archive and select the earliest chronological 2017 game that has:

- a box score;
- a recap;
- at least one SDSU batting line;
- at least one SDSU pitching line.

Create one small committed configuration file describing only that game’s sources:

```text
config/2017/one_game.json
```

Each source entry needs only:

- stable source ID;
- original SDSU URL;
- source kind: `box_score` or `recap`;
- expected SHA-256 after the initial reviewed fetch.

Do not create a complete source inventory or discovery framework.

### Minimal implementation shape

Likely application files:

```text
src/defiance/
├── cli.py
├── fetch.py
├── parse.py
├── db.py
└── query.py
```

Keep box-score and recap parsing in `parse.py` until real format differences make separate adapter modules worthwhile.

Implement two CLI operations:

```text
defiance build-slice
defiance show-game <game-id>
```

`build-slice` performs fetch, preservation, parsing, normalization, validation, and SQLite loading.

`show-game` prints:

- game date and opponent;
- final score;
- normalized batting and pitching lines;
- a short recap passage;
- the original SDSU URL supporting each result.

This is a deterministic inspection command, not a natural-language interface.

### Raw preservation

For each configured source:

- Fetch the response bytes with an explicit timeout and redirect handling.
- Calculate SHA-256 before parsing.
- Store the unchanged bytes under `data/raw/` using the source ID and hash.
- Refuse to overwrite existing bytes.
- Reuse an existing file when its hash matches.
- Fail explicitly when downloaded bytes do not match the committed expected hash.

Do not implement:

- generalized source versioning;
- automatic version selection;
- changed-source review states;
- remote evidence storage;
- a full fetch-history database.

The raw filename, committed hash, original URL, and SQLite source row provide sufficient evidence for this milestone.

### Parsing and normalization

Parse only the fields needed to prove the slice:

- game date;
- opponent;
- SDSU and opponent scores;
- player names present in the selected box score;
- SDSU batting lines available in that box score;
- SDSU pitching lines available in that box score;
- one or more ordered recap passages.

Do not ingest the roster, schedule, season statistics, play-by-play, series, or tournament structure.

Use the Python standard library initially. Add one parsing dependency only if inspection of the selected documents shows that the standard library would make the parser fragile or substantially more complex. Any such dependency requires a named proposal before installation.

### Minimal SQLite schema

Use only six tables:

- `sources`
  - source ID, kind, original URL, SHA-256, and raw path.
- `games`
  - game ID, date, opponent text, SDSU score, opponent score, source ID, and source locator.
- `players`
  - player ID, full name, source ID, and source locator.
- `batting_lines`
  - game ID, player ID, parsed batting values, source ID, and source locator.
- `pitching_lines`
  - game ID, player ID, parsed pitching values, source ID, and source locator.
- `recap_passages`
  - game ID, passage order, text, source ID, and source locator.

Use foreign keys and uniqueness constraints.

Store innings pitched as integer outs if the selected source includes fractional innings.

Row-level `source_id` and `source_locator` are sufficient provenance for this slice. Do not build per-field provenance or a generic provenance table.

### Database loading

Use one ordinary SQLite transaction:

1. Create the six tables if needed.
2. Replace the selected game’s normalized rows.
3. Run validation.
4. Commit if validation succeeds.
5. Roll back on failure.

This provides safe reruns without introducing:

- temporary corpus databases;
- atomic file promotion;
- corpus versions;
- build registries;
- schema migration tooling;
- release pointers.

Running the slice twice against identical raw evidence must not create duplicate rows or change query results.

### Validation

Validation is code tailored to this one source format, not a generalized validation framework.

The build must fail with a nonzero exit when:

- a configured raw file is missing;
- its hash differs from configuration;
- a parser returns no game;
- the game score is missing or invalid;
- no batting or pitching lines are found;
- a stat line references an unknown player;
- duplicate players or stat lines occur for the same game;
- a normalized row lacks a valid source;
- required source locators are absent;
- foreign-key or database integrity checks fail.

Where the selected box score exposes team totals, compare them with the parsed player totals. Implement only checks supported by the real document.

Validation output may be plain terminal text. Do not create validation tables, reports, severities, review workflows, or conflict-resolution configuration in this milestone.

If the box score and recap expose contradictory high-risk facts, fail and report both sources. Do not build a general conflict model.

### Query and provenance acceptance

`show-game` must query SQLite rather than parsed in-memory objects.

For every displayed result, it must be possible to identify:

- the normalized SQLite row;
- the preserved raw file;
- the relevant source locator;
- the original public SDSU URL.

No web application, API, FTS index, natural-language routing, or answer formatter is included.

### Tests

Add only the tests required to protect the slice:

- A box-score fixture parser test with exact expected score and stat lines.
- A recap fixture parser test with exact expected passage ordering.
- An offline end-to-end test:
  - fixture bytes;
  - parse;
  - normalize;
  - validate;
  - SQLite load;
  - query;
  - provenance lookup.
- A failure test using a deliberately altered or incomplete fixture.
- An idempotency test proving a second build creates no duplicates and returns the same normalized values.

Small source fixtures may be committed with their original URL and hash. Full raw documents remain ignored.

Add basic CI with the milestone tests, not before tests exist. CI must use `uv` and must not contact SDSU.

### Acceptance criteria

Milestone 1 is complete when:

- Two real SDSU documents have been preserved byte-for-byte.
- Their hashes match committed configuration.
- The selected game, players, batting lines, pitching lines, and recap passages exist in SQLite.
- All rows have row-level source provenance.
- The CLI retrieves normalized results and original SDSU URLs.
- Validation rejects a known-bad fixture.
- A repeated build is idempotent.
- All offline tests pass.
- The final diff contains no web, deployment, model, series, event, lifecycle, or generalized provenance infrastructure.

### Explicitly deferred

- Complete 2017 source discovery.
- Source-version lifecycle management.
- Atomic corpus publication.
- Ingest-run and validation-issue tables.
- Per-field or generic provenance.
- Source-conflict resolution workflows.
- Roster identity and alias systems.
- Opponent, series, and tournament abstractions.
- Season statistics and multi-game aggregation.
- Narrative search and FTS5.
- Natural-language questions and quick hitters.
- Runtime usage logging.
- Web UI and hosting.
- Model providers, embeddings, and agents.
- ORM, migration framework, and production database lifecycle.

Suggested milestone commit:

`feat: ingest and validate one 2017 SDSU game`
