# Code conventions and runtime plumbing

Type: grilling
Status: resolved
Blocked by: —
Assignee: Saul

## Question

Which code conventions should M0 lock in? Decide:
- **Package layout:** under `src/phy/`.
- **CLI framework:** Typer?
- **Database access:** raw `sqlite3` or a thin layer, and how the schema is migrated.
- **Config:** loading and validating `config.toml` and `questions.yaml`.
- **Logging.**
- **Testing:** recorded OAI-PMH and API fixtures, no live calls by default, and one opt-in live smoke test.
- **Credentials:** how the API key reaches the launchd job. QUICK_START currently says `~/.zshenv`, which is wrong because launchd doesn't read shell profiles. The options are an `ant auth login` profile, the plist's `EnvironmentVariables`, a gitignored `.env`, or the macOS Keychain.
- **Locking:** the lock-file mechanics for `phy daily` and for the arXiv rate limiter.

## Answer

Grilled with the Reader on 2026-10-25. Recorded in SPEC §3 (Assumptions), §5 (Components), §6 (Files and data) and QUICK_START §1, §5, §9.

**Installation home (added by this ticket).** All instance state lives in `$PHY_HOME`, default `~/.phy-agent-platform`, overridden by the `PHY_HOME` env var (convention over configuration). It holds the data (`phy.db`, `papers/`, `golden_sources/`, `runs/`, `logs/`, the locks) **and** the instance config (`config.toml`, `questions.yaml`, `golden/`, `CHANGELOG.md`). The repo keeps code, `prompts/` and `schemas/`. `config.py` resolves one `Paths` object, and no other module has path literals. `phy init` seeds the config files from `src/phy/defaults/` (QUICK_START knob defaults, the 4 questions of SPEC §4, an empty manifest and changelog) without overwriting anything, and runs `git init` on `$PHY_HOME` with the data gitignored. phy never commits.

**Layout.** Flat modules under `src/phy/`: `cli, config, db, arxiv, watch, filter, read/, verify, eval, card, llm, tracer, locks, ui/`, plus `migrations/` and `defaults/`. A subpackage only where a Stage needs more than one file (`read/`: Stage, flatten, source detection; `ui/`). Stages are plain functions `run(ctx, …)`, and `ctx` carries config, db, Tracer and run_id.

**CLI.** Typer. `cli.py` only parses and calls; tests call the functions directly.

**Database.** Raw `sqlite3`, with named query functions in `db.py`. `connect()` sets WAL, `busy_timeout`, `foreign_keys=ON` and `sqlite3.Row`. Migrations are numbered `migrations/NNN_<name>.sql` files, tracked with `PRAGMA user_version`, applied in a transaction automatically on connect. There are no down-migrations.

**Config.** `tomllib` and PyYAML into Pydantic models with `extra="forbid"`, loaded once per command into `ctx`. Invalid config fails before any work. No env overrides except `PHY_HOME` and the SDK's own credential variables.

**Logging.** structlog, with stdlib logging routed through `ProcessorFormatter`. Human-readable `ConsoleRenderer` on stderr (colour only on a TTY), and JSONL to `$PHY_HOME/logs/phy-YYYY-MM-DD.jsonl`, 30 days kept.
- Event names are fixed `<area>.<past_tense>` strings, with variables in keys. `run_id`, `stage`, `arxiv_id` and `version` are bound through contextvars.
- Levels: ERROR when someone must look; WARNING when degraded but continuing; INFO for Stage start and finish plus one line per paper outcome, at most about 30 lines per normal `phy daily`; DEBUG per request, only with `-v`.
- `httpx`, `httpcore`, `anthropic` and `urllib3` are capped at WARNING. Never logged: secrets, prompt or response bodies, abstracts, quote text. An exception is logged once, where it's handled.
- **SQLite first:** every pipeline metric, tile and the budget come from SQLite. Logs carry only operational metrics (durations, retries, rate-limiter waits, lock contention), with the unit in the key name.

**Testing.** pytest. respx replays HTTP for both OAI-PMH and the Anthropic SDK, so `messages.parse()` validation runs for real. Fixtures: the OAI XML on `research/oai-pmh-client`, the recorded Read response on `prototype/card-schema-read-prompt`, and a synthetic `.tex` we write ourselves (no arXiv tarball in git). No network by default; `-m live` runs one paid smoke test (Read on 1904.12072, about $0.10). An autouse fixture sets `PHY_HOME=tmp_path`.

**Credentials.** phy has no credential code; the SDK's lookup chain decides. The documented default is `ant auth login`: the SDK reads `~/.config/anthropic/{active_config,configs,credentials}` with only HOME set and refreshes the token itself, so it works under launchd. `ANTHROPIC_API_KEY` still wins when set. Ruled out: a key in plist `EnvironmentVariables` (world-readable plist, printed by `launchctl print`), `.env` and Keychain code. `phy init` makes one cheap auth call and reports the source used. Still to check once `ant` is installed: the full login flow end to end, and how OAuth usage is billed and capped compared with a Console API key.

**launchd.** `phy schedule install` writes the plist: the absolute `uv` path (launchd's PATH is `/usr/bin:/bin:/usr/sbin:/sbin` and it never reads `~/.zshenv`), `WorkingDirectory` set to the repo, `PHY_HOME` in `EnvironmentVariables`, and `StandardErrorPath` at `$PHY_HOME/logs/launchd.err` for crashes before logging starts.

**Locks.** `fcntl.flock`, released on process death, so locks never go stale.
- `$PHY_HOME/phy.lock` is non-blocking. It is taken by `daily` and every Stage command, including `read --paper`. If it is held, the command logs and exits 0. `ui` and `status` never take it.
- `$PHY_HOME/arxiv.lock` is blocking. The process reads the last request time from the file, sleeps until `arxiv.min_interval_s` has passed, makes the request while holding the lock, writes the new time, then releases. Backoff sleeps also happen inside the lock.

**Toolchain.** Python 3.13 (`.python-version`, `requires-python >=3.13`) with uv. `ruff` format and lint; no type checker in M0. Runtime dependencies: `anthropic, httpx, lxml, pydantic, pyyaml, typer, structlog, fastapi, uvicorn, jinja2, pypdfium2, pillow` (pillow added by build slice 06: pypdfium2 needs it to write PNGs). Dev: `pytest, respx, ruff`.

**No ADR.** These are conventional and cheap to reverse. Nothing for GLOSSARY.md: they are implementation terms.
