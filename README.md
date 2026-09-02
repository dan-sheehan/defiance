# Defiance

Defiance V1 is a source-backed historical system for the 2017 San Diego State
baseball season. V1 is limited to material currently archived by SDSU.

The first milestone proves one complete, deterministic path:

```text
SDSU source → preserved bytes → normalized SQLite rows → inspected result
```

## Milestone 1

Milestone 1 contains only SDSU's February 17, 2017 game against Pacific. The
game was suspended and completed February 18, but the legacy box report's game
metadata identifies it as the February 17 game. The combined recap is reduced
to the ordered passages about that opener. Play-by-play is not ingested.

The two configured sources are:

- [Legacy SDSU box score](https://sandiegost_ftp.sidearmsports.com/custompages/sports/m-basebl/stats/021817aaa.html)
- [SDSU recap](https://goaztecs.com/news/2017/02/18/aztecs-win-halted-game-drop-nightcap-to-pacific)

The legacy host has a certificate hostname incompatibility. Defiance retains
certificate-chain validation but disables hostname matching only for that exact
box-score host, refuses cross-host redirects, and requires the reviewed SHA-256.

## Development

The repository uses Python 3.12 and [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync --locked --no-editable
uv run --no-sync defiance build-slice
uv run --no-sync defiance show-game 2017-02-17-pacific
uv run --no-sync python -m unittest discover -s tests
```

`build-slice` contacts the two configured SDSU sources. The test suite is fully
offline. Downloaded source documents and generated SQLite databases stay out
of Git.

Defiance-authored code is covered by this repository's MIT license. SDSU source
material remains the property of its original publisher and is preserved only
as local evidence or small test fixtures.
