# Defiance

Defiance V1 is a source-backed historical system for the 2017 San Diego State
baseball season. V1 is limited to material archived on the SDSU website.

The data path is deterministic:

```text
SDSU sources → preserved bytes → normalized rows → validation → SQLite
```

## Run locally

Use Python 3.12 and [`uv`](https://docs.astral.sh/uv/getting-started/installation/).
Run all commands below from the repository root. `uv sync --locked` installs the
package and its dependencies; no `PYTHONPATH` setting or frontend build is needed.

```bash
git clone https://github.com/dan-sheehan/defiance.git
cd defiance
uv sync --locked
uv run --no-sync defiance --help
uv run --no-sync python -m unittest discover -s tests -v
```

The initial tests run offline using committed fixtures. Tests requiring the full
preserved corpus or a built database skip until that data is available. The
separate pinned release-artifact test also skips unless explicitly enabled.

### Acquire sources, then build and validate

Raw SDSU documents and generated databases are not included in Git. If you
already have the preserved files named in `config/2017/corpus.json` under
`data/raw/`, skip acquisition and go straight to the offline build commands.
Otherwise, acquire the sources:

```bash
uv run --no-sync defiance inventory-corpus
git diff -- config/2017/corpus.json
```

`inventory-corpus` requires network access to SDSU. It rediscovers the archive,
preserves downloaded bytes, and **rewrites `config/2017/corpus.json`**, including
source hashes. It is not a download of the committed hash-pinned corpus. Review
any inventory changes before treating the downloaded evidence as the reviewed
corpus. Archive availability or source changes can prevent acquisition or
validation; do not bypass failures or accept changed hashes automatically.

Build and validate offline, then rerun the tests with the full corpus available:

```bash
uv run --no-sync defiance build-corpus
uv run --no-sync defiance validate-corpus
uv run --no-sync python -m unittest discover -s tests -v
```

Both corpus commands verify every available in-scope raw file against its
inventory SHA-256. `build-corpus` parses and validates the evidence before
loading `data/normalized/2017.sqlite3`; `validate-corpus` checks the existing
database against the preserved evidence and normalized-corpus rules. Missing
raw files, changed bytes, or invalid data cause explicit failures. Keep the raw
files for future validation. Normal validation does not require the byte-level
hash of a particular deployed SQLite artifact.

### Use the CLI and web app

```bash
uv run --no-sync defiance show-game 2017-04-15-unlv
uv run --no-sync defiance ask "How many home runs did Danny Sheehan hit in 2017?"
uv run --no-sync flask --app 'defiance.web:create_app()' run
```

The CLI example should answer **7 home runs** with source links. Open
[http://127.0.0.1:5000](http://127.0.0.1:5000) for the web app; stop the local
server with Ctrl+C. It requires the built corpus and creates a separate writable
`data/runtime/audit.sqlite3` for request audits. The corpus is read-only during
questions and health checks. See [Mobile web application](#mobile-web-application)
for path overrides and audit contents.

### Optional exact release-artifact verification

Ordinary full-corpus tests build and validate local data without a release hash.
To check an existing copy of the exact pinned Railway artifact, explicitly
supply its path:

```bash
DEFIANCE_TEST_RELEASE_CORPUS="/path/to/pinned-release.sqlite3" \
  uv run --no-sync python -m unittest discover -s tests -p test_production.py -v
```

This test copies the supplied artifact to temporary local storage and calls the
unchanged production preflight with its exact pinned SHA-256. A missing,
corrupt, or different supplied artifact fails; no artifact is fetched or
deployed. Omit `DEFIANCE_TEST_RELEASE_CORPUS` for normal local testing. A valid
local rebuild need not have the same SQLite file bytes as the pinned release.

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

By default the server resolves paths from the current working directory, reads
`data/normalized/2017.sqlite3`, and writes anonymous request audits to
`data/runtime/audit.sqlite3`. Override those paths with
`DEFIANCE_CORPUS_DATABASE` and `DEFIANCE_AUDIT_DATABASE`. They must resolve to
different files. The corpus is opened read-only throughout the answer and
health paths; only the runtime audit database is writable.

Run the local development server after building the validated corpus:

```bash
uv run --no-sync flask --app 'defiance.web:create_app()' run
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

## CLI notes

`ask` reads the generated full-corpus database and prints a short answer first,
followed by compact source references and independently parseable suggestions
when useful. Routing failures are exposed by the returned `AnswerResult` for
offline evaluation; no private-testing threshold or automatic model-provider
trigger is encoded in the application.

`show-game` reads `data/normalized/2017.sqlite3`, the completed full corpus.
The historical `build-slice` command fetches two sources and writes a separate
`data/normalized/milestone1.sqlite3`; it is not a prerequisite for the current
application, and `show-game` does not read that slice database.

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

## Railway operator reference

These existing instructions apply to one pinned release artifact, not local
setup. Hosting prices and provider behavior below are historical notes and
must be rechecked before a deployment. A freshly built local corpus is not a
substitute for the pinned artifact. No Railway account is needed to run locally.

<details>
<summary>Existing release deployment, audit export, and rollback instructions</summary>

## Production deployment on Railway

The V1 production target is one Railway Hobby service in US West, one persistent
volume mounted at `/data`, and the Railway-provided HTTPS domain. Railpack builds
the package from `pyproject.toml` and `uv.lock` with Python 3.12 and `uv`.
Gunicorn runs the existing `defiance.web:create_app()` factory with one
synchronous worker; the Flask development server is never used in production.
No Dockerfile, database server, worker service, model provider, or secret is
needed.

`railway.json` sets mode `0444` on the single pinned corpus filename and runs
`python -m defiance.production` before Gunicorn on every start. The explicit
mode step is necessary because Railway's SFTP-based volume upload copies file
bytes but not the local POSIX mode. It cannot target an environment-controlled
path. A missing file or failed mode change stops the shell, and the independent
preflight then refuses to start unless all of these conditions hold:

- Railway reports the mounted volume at exactly `/data`, and both configured
  database paths resolve inside it and are distinct;
- the corpus is a regular file with mode `0444` and SHA-256
  `295f6fb5325f8b82be2d8a12d2ae7106f70560824aca4394c483850d9b6c3245`;
- the corpus passes SQLite `integrity_check`, `foreign_key_check`, a real FTS5
  query, and Defiance's complete normalized-corpus validation while opened in
  SQLite read-only mode;
- a second hash after validation proves the corpus did not change; and
- `/data/audit.sqlite3` can be initialized to the current schema, restricted to
  mode `0600`, and locked for a test write transaction.

The configured health check is `GET /healthz` with a 60-second deployment
timeout. It verifies both databases and returns only `{"status":"ok"}` or the
generic unavailable response. A missing or corrupt corpus or unusable audit
volume prevents Gunicorn from starting. Railway retries a crashed service up to
10 times. Railway health checks gate deployments but are not continuous
monitoring, and a volume-backed service has brief downtime during a deployment
because two deployments cannot mount the volume concurrently.

### First deployment

First validate the exact local artifact and the complete checkout without
rebuilding or contacting SDSU:

```bash
uv sync --locked
uv run --no-sync defiance validate-corpus
uv run --no-sync python -m unittest discover -s tests -v
shasum -a 256 data/normalized/2017.sqlite3
```

The final command must print the pinned SHA-256 above. In the Railway dashboard,
select the Hobby plan and create an empty project. Install and authenticate the
Railway CLI separately, then link this checkout, create the empty service, and
place its single replica in US West before connecting its GitHub source:

```bash
railway login
railway link
railway add --service defiance
railway service defiance
railway service scale us-west=1
railway volume add --mount-path /data
railway volume list
```

Copy the single volume's name from `railway volume list` into
`DEFIANCE_VOLUME`. Upload a copy of the already validated database to a
hash-versioned name. The leading `/` used by `railway volume files` is the
volume root, which Railway mounts at `/data` for the service. The start command
applies mode `0444` to this exact pinned filename before the strict preflight.
Do not use `--overwrite`, do not upload `data/raw`, and do not run
`build-corpus` in the deployment:

```bash
DEFIANCE_CORPUS_SHA=295f6fb5325f8b82be2d8a12d2ae7106f70560824aca4394c483850d9b6c3245
DEFIANCE_CORPUS_NAME="2017-${DEFIANCE_CORPUS_SHA}.sqlite3"
DEFIANCE_VOLUME="<name from railway volume list>"
DEFIANCE_UPLOAD_DIR="$(mktemp -d)"
test "$(shasum -a 256 data/normalized/2017.sqlite3 | awk '{print $1}')" = "$DEFIANCE_CORPUS_SHA"
cp data/normalized/2017.sqlite3 "$DEFIANCE_UPLOAD_DIR/$DEFIANCE_CORPUS_NAME"
chmod 0444 "$DEFIANCE_UPLOAD_DIR/$DEFIANCE_CORPUS_NAME"
railway volume files --volume "$DEFIANCE_VOLUME" upload "$DEFIANCE_UPLOAD_DIR/$DEFIANCE_CORPUS_NAME" "/$DEFIANCE_CORPUS_NAME"
railway volume files --volume "$DEFIANCE_VOLUME" list / --json
railway volume files --volume "$DEFIANCE_VOLUME" download "/$DEFIANCE_CORPUS_NAME" "$DEFIANCE_UPLOAD_DIR/downloaded-$DEFIANCE_CORPUS_NAME"
test "$(shasum -a 256 "$DEFIANCE_UPLOAD_DIR/downloaded-$DEFIANCE_CORPUS_NAME" | awk '{print $1}')" = "$DEFIANCE_CORPUS_SHA"
```

Set exactly these application/build variables. `PORT` and
`RAILWAY_VOLUME_MOUNT_PATH=/data` are injected by Railway; do not set either
manually. Flask debug mode must remain unset, and no Flask secret, LLM key, or
model-provider credential exists for V1.

```bash
railway variable set --service defiance --skip-deploys \
  RAILPACK_PYTHON_VERSION=3.12 \
  DEFIANCE_CORPUS_DATABASE="/data/$DEFIANCE_CORPUS_NAME" \
  DEFIANCE_CORPUS_SHA256="$DEFIANCE_CORPUS_SHA" \
  DEFIANCE_AUDIT_DATABASE=/data/audit.sqlite3
railway variable list --service defiance --kv
```

After the deployment commit is on `main`, connect the private GitHub repository.
In the service settings, confirm `main` as the deploy trigger and enable **Wait
for CI** so a failed existing GitHub workflow skips deployment. Review Railway's
staged configuration, deploy it, and generate the Railway HTTPS domain:

```bash
railway service source connect --repo dan-sheehan/defiance --branch main --service defiance
railway service logs --service defiance --deployment --latest
railway domain --service defiance
```

The first successful startup creates only `/data/audit.sqlite3`; the corpus
artifact is never copied into the image and its bytes are never modified.
Confirm the startup log contains the pinned hash and no private filesystem path,
then run the release validation below.

### Logs, privacy, and cost

Application audit data is the private SQLite content described above. Gunicorn
access logging is explicitly sent to `/dev/null`, so Defiance does not duplicate
request IP addresses, user agents, or request lines in process logs. Process
stdout/stderr contains only Gunicorn lifecycle/errors and the safe preflight
result; it must not contain questions or database paths.

Railway's infrastructure HTTP logs are separate from both stores and expose
provider fields for source IP and client user agent. Railway documents seven-day
log retention for Hobby. This metadata is an accepted hosting limitation; this
deployment does not claim it can be disabled and does not add a log drain,
analytics vendor, or second copy.

The expected low-traffic bill is approximately the $5/month Hobby minimum,
which includes the first $5 of usage. Railway currently lists memory at
$10/GB-month, CPU at $20/vCPU-month, volume storage at $0.15/GB-month, and
service egress at $0.05/GB. The roughly 4 MB corpus plus a small audit database
has negligible storage cost. Sustained traffic, memory/CPU time, audit growth,
egress, or extra services/environments can increase the bill. This deployment
does not enable Railway's agent; Defiance itself makes no model call and creates
no usage-based LLM charge. Review Railway usage after the first week and set a
workspace spending limit if desired.

### Private audit export

Never download the live writable `/audit.sqlite3` file directly while the
service is accepting requests. Instead, use SQLite's backup API over Railway SSH
to create a transactionally consistent, mode-`0600` snapshot on the private
volume, download that snapshot with `railway volume files`, verify it, and then
delete the remote snapshot:

```bash
DEFIANCE_VOLUME="<name from railway volume list>"
DEFIANCE_AUDIT_EXPORT_DIR="$(mktemp -d)"
railway ssh --service defiance -- python -c 'from pathlib import Path; import os, sqlite3; snapshot = Path("/data/audit-export.sqlite3"); snapshot.unlink(missing_ok=True); source = sqlite3.connect("file:/data/audit.sqlite3?mode=ro", uri=True); target = sqlite3.connect(snapshot); source.backup(target); target.close(); source.close(); os.chmod(snapshot, 0o600)'
railway volume files --volume "$DEFIANCE_VOLUME" download /audit-export.sqlite3 "$DEFIANCE_AUDIT_EXPORT_DIR/audit.sqlite3"
chmod 0600 "$DEFIANCE_AUDIT_EXPORT_DIR/audit.sqlite3"
uv run --no-sync python -c 'import sqlite3, sys; connection = sqlite3.connect(sys.argv[1]); print(connection.execute("PRAGMA integrity_check").fetchone()[0]); print(connection.execute("SELECT COUNT(*) FROM ask_requests").fetchone()[0]); connection.close()' "$DEFIANCE_AUDIT_EXPORT_DIR/audit.sqlite3"
railway volume files --volume "$DEFIANCE_VOLUME" delete /audit-export.sqlite3
```

The integrity result must be `ok`. Keep the downloaded snapshot private. The
application and Railway operator are the only intended readers/writers; there is
no public route, static link, TCP proxy, or admin interface for either database.

### Rollback

For an application regression, select the last known-good Railway deployment
and redeploy it, or revert the bad Git commit on `main`. Leave the volume and
audit database attached. A failed startup or `/healthz` check is marked failed;
restore the last known-good variables/deployment and inspect only the generic
preflight category before retrying.

Corpus artifacts are immutable and hash-versioned. Never overwrite or delete
the active artifact during a rollback. To restore a previous approved corpus,
upload that validated artifact under its own hash name, deploy the matching
application revision whose pinned hash agrees, and change the corpus path and
hash variables together. The audit database is not rolled back with application
code. No custom release service is required.

### Post-deploy release validation

Set `DEFIANCE_URL` to the generated `https://...up.railway.app` origin. Verify
the transport first:

```bash
curl --fail-with-body --silent --show-error "$DEFIANCE_URL/healthz"
curl --fail-with-body --silent --show-error "$DEFIANCE_URL/" >/dev/null
```

`/healthz` must return HTTP 200 with `{"status":"ok"}`, and the homepage must
load its packaged CSS and JavaScript over HTTPS without a debug page. In a fresh
browser session, submit this exact matrix and record every returned request ID:

| Check | Exact question | Expected result |
| --- | --- | --- |
| Full-name quick hitter | `Danny Sheehan` | answered; 1–5 deterministic bullets, including Air Force road series and a 4-for-5 game |
| Season hitter | `How many home runs did Danny Sheehan hit in 2017?` | answered; 7 home runs |
| Season pitcher | `How many strikeouts did Brett Seeburger have in 2017?` | answered; 69 strikeouts |
| Opponent aggregation | `What did Danny Sheehan hit against UNLV in 2017?` | answered; 9-for-25, .360, six games |
| Series query | `What did Danny Sheehan hit in the road series at UNLV?` | answered; 5-for-13, .385, four RBI |
| Tournament query | `What was SDSU's record in the Mountain West Tournament?` | answered; 3-1 |
| Narrative query | `What did the recap say about Danny Sheehan in the June 3 UCLA game?` | answered; hit by pitch and winning run |
| Ambiguous name | `What were Brown's 2017 stats?` | `ambiguous_entity`; names Andrew Brown and Tre Brown, with no partial fact |
| Unavailable data | `How many hits did Danny Sheehan have against Fresno State?` | `unavailable`; explains the missing box score, with no partial aggregate |
| Unsupported question | `What was SDSU's batting average with runners in scoring position?` | `unsupported` |
| Off-topic question | `What was the weather in San Diego?` | `off_topic` |

For every answered result, verify at least one evidence link is rendered, uses
HTTPS, and targets only `goaztecs.com` or
`sandiegost_ftp.sidearmsports.com`. From the `Danny Sheehan` quick hitter, click
the rendered `What was Danny Sheehan's best series?` suggestion and verify the
new independent response identifies the Air Force road series. Then submit the
second independent question `What was SDSU's conference record?` and verify
20-10; neither response may depend on earlier text.

Create and download a consistent audit snapshot using the procedure above.
Verify that all recorded request IDs and exact questions appear once in
`ask_requests` with their expected status/intent, answered requests have their
evidence rows in `ask_evidence`, and the schema has no IP-address, user-agent,
cookie, account, or cross-request identity column.

Finally download the active corpus again and confirm both immutability and the
absence of SQLite write sidecars:

```bash
DEFIANCE_CORPUS_SHA=295f6fb5325f8b82be2d8a12d2ae7106f70560824aca4394c483850d9b6c3245
DEFIANCE_CORPUS_NAME="2017-${DEFIANCE_CORPUS_SHA}.sqlite3"
DEFIANCE_VOLUME="<name from railway volume list>"
DEFIANCE_VERIFY_DIR="$(mktemp -d)"
railway volume files --volume "$DEFIANCE_VOLUME" download "/$DEFIANCE_CORPUS_NAME" "$DEFIANCE_VERIFY_DIR/$DEFIANCE_CORPUS_NAME"
test "$(shasum -a 256 "$DEFIANCE_VERIFY_DIR/$DEFIANCE_CORPUS_NAME" | awk '{print $1}')" = "$DEFIANCE_CORPUS_SHA"
railway volume files --volume "$DEFIANCE_VOLUME" list /
```

The volume listing must not contain a `-journal`, `-wal`, or `-shm` file for the
corpus. It may contain transient SQLite files for the separate writable audit
database while requests are active.

</details>
