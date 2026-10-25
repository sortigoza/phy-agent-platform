# Skeleton and phy init

Type: AFK
Status: done
Blocked by: —

## Goal

An installable `phy` package whose `phy init` creates a working `$PHY_HOME`, with the plumbing every later slice relies on: paths, config, logging, locks and the database.

## Sources

SPEC §3 Assumptions, §5 Runtime / Installation home / Logging / Storage, §6 (tree, `phy init`, config loading); QUICK_START §1–2 and the config table; [Code conventions and runtime plumbing](../../m0/issues/07-code-conventions.md).

## Acceptance criteria

- `uv sync` then `uv run phy --help` works on Python 3.13; ruff and pytest are configured in `pyproject.toml`.
- `phy --version` prints `git describe --tags --always` of the running checkout (a commit hash until a tag exists).
- `config.py` resolves `$PHY_HOME` (default `~/.phy-agent-platform`) once into a `Paths` object; no other module builds paths.
- `config.toml` and `questions.yaml` load into Pydantic models with `extra="forbid"`, once per command; an unknown or invalid key fails the command before any work, naming the key.
- `phy init` creates `$PHY_HOME`, seeds `config.toml` (QUICK_START defaults), `questions.yaml` (the 4 questions of SPEC §4, with keywords, negative keywords and `scope_notes`), an empty `golden/manifest.yaml`, `CHANGELOG.md` and `.gitignore` from `src/phy/defaults/`; it never overwrites an existing file and runs `git init` only if there is no repo. Running it twice changes nothing.
- `phy init` makes one cheap API call (Haiku, a few tokens) and reports which credential source the SDK used; a missing credential is a clear error pointing at `ant auth login`.
- structlog: readable lines on stderr plus JSON lines in `$PHY_HOME/logs/phy-YYYY-MM-DD.jsonl`, 30 days kept; `-v` enables DEBUG; noisy libraries capped at WARNING; `run_id`, `stage`, `arxiv_id`, `version` bindable through contextvars.
- `locks.py`: the non-blocking `phy.lock` (held → log and exit 0) and the blocking `arxiv.lock` helper, both `fcntl.flock`.
- `db.py`: connect in WAL mode with `busy_timeout`, apply `migrations/NNN_*.sql` in order tracked by `PRAGMA user_version`. Migration `001_state` creates `state` and `runs` (every later slice records runs).
- The `Ctx` object (config, db, Tracer slot, run_id) that Stage functions `run(ctx, …)` receive exists.

## Tests first

- `PHY_HOME` override and default; `Paths` fields.
- Config: defaults load; unknown key rejected; invalid value rejected with its path.
- `phy init`: creates every file; second run is a no-op and leaves edited files untouched; `git init` once (auth call mocked with respx).
- Migrations: fresh db reaches the latest `user_version`; re-connect applies nothing; a new numbered file is applied once.
- Locks: a second non-blocking acquire in another process returns "held" and the command exits 0.
- Logging: an event lands in both sinks with bound context; secrets-like keys are not logged.

## Lift from

Nothing; conventions come from the code-conventions ticket.

## Not in this slice

Any Stage, the Tracer implementation (slice 03), `phy status` (slice 10), `phy schedule` (slice 11).
