# Physics Agent Platform — v1 Spec

Revised 2026-10-25 from the original "Paper Reading Platform — v1 Spec" draft after a design review. Vocabulary is defined in [`GLOSSARY.md`](../GLOSSARY.md); capitalised terms (Card, Flag, Golden set, ...) mean exactly what it says. Decisions that are hard to reverse are recorded in [`docs/adr/`](adr/).

## 1. Purpose and success criteria

v1 succeeds when the Reader absorbs 30 relevant papers a week with no more than about 4.5 hours of their own time, and trusts what they absorb. Today they read about 1 paper a week in full. The platform does not make them read 30 papers in full. It changes what "reading" means, and spends attention only where it matters.

| Reading level | Who does it | What the Reader gets | Reader time per paper | Target per week |
| --- | --- | --- | --- | --- |
| L0 Screened | Agents only | Relevance score and a one-line reason | 0 min | all Candidates |
| L1 Carded | Agents read, Reader reviews | A verified Card | 4–5 min | 30 |
| L2 Deep read | Reader, Card as guide | Full understanding, own notes | 45–60 min | 1–2 |

**The arithmetic.** 30 Cards × 5 min = 2.5 h. Two deep reads add up to 2 h. That totals about 4.5 h, so Card review must stay near 4 minutes. That number drives the Card design.

**Success criteria** (measured at the end of week 4 after M1 ships):

- **Throughput:** ≥ 30 Cards reviewed per week for 2 consecutive weeks.
- **Card accuracy:** ≥ 90% of Card fields correct on the Trusted Golden set.
- **Grounding:** every factual Card field has Evidence or is visibly marked unsupported.
- **Filter precision:** ≥ 70% of reviewed Cards rated relevant.
- **Filter recall:** ≤ 1 in 10 papers found by other means was missed by the pipeline.
- **Attention:** median review time ≤ 5 min, measured by the review UI.
- **Learning check:** each month the Reader can name ≥ 3 ideas learned through the pipeline that they would otherwise have missed.

## 2. Principles

1. **One Workload, done properly.** v1 is the paper-reading Workload. "Platform" is the shape every Workload shares: Stages → tables → Instruments → Golden set → Meta-work. It gets extracted when a second Workload exists, not before.
2. **Simplest thing that runs unattended.** Native Python, one SQLite file, plain text files. No Docker, no Postgres, no Langfuse in v1. Each of these is easy to add later.
3. **Stages are function calls, not agents.** Every Stage is plain code plus at most one structured Messages API call per item. The Agent SDK is reserved for Meta-work ([ADR-0001](adr/0001-plain-api-calls-for-stages-agents-for-meta-work.md)).
4. **Code checks before model checks.** A string match cannot hallucinate. Model reviewers only judge what code cannot.
5. **Fix the system, not the output.** Cards are never hand-edited. Flags feed Meta-work, and Meta-work is gated by the Golden set.
6. **Every Stage is idempotent and catches up.** Each Stage processes "all rows not yet processed", never "today's rows". A missed or failed run is repaired by the next one.

## 3. Scope and milestones

### Assumptions

- **User:** a single Reader. No authentication; everything binds to `localhost`.
- **Machine:** an Apple Silicon Mac with ≥ 16 GB RAM. Python 3.13 managed by `uv`.
- **Model access:** the Anthropic Python SDK, which finds credentials itself: `ANTHROPIC_API_KEY` if set, otherwise the `ant auth login` profile in `~/.config/anthropic/` (the documented default, because it works under launchd). phy has no credential code.
- **Source:** arXiv is the only source, harvested with OAI-PMH. LaTeX source is preferred and PDF is the fallback.

### Milestones

| Milestone | Delivers | Exit criteria |
| --- | --- | --- |
| **M0: Cards on screen** (target ≈ 1 week of building) | Watch (OAI-PMH, high-water mark), Filter, Read, Verify (code checks only), review UI, Monitoring page, run viewer, Golden eval on ≤ 4 Placeholder Dev Papers (code checks plus run-to-run diff), weekly spend guardrail, launchd schedule | First Card for arXiv:1904.12072 reviewed in the UI. 7 consecutive days of unattended runs with the high-water mark advancing. Every M0 Instrument tile populated. |
| **M1: Trust** | Model reviewer in Verify. Model-judged field accuracy on Trusted Papers. Held-out split. Missed-papers log. macOS notifications. "Deep read blind" toggle. Batch API switch. Attention-budget tile: Reader minutes per week (Reviews, deep reads, upkeep) against the 4.5 h budget, once deep-read and Meta-work minutes are recorded. | ≥ 1 Trusted Golden Paper. Success criteria measurable. |
| **M2: Synthesis and meta-agents** | Synthesize (claims, contradictions), weekly Digest, Improver agent (Agent SDK), optional Langfuse via the Tracer interface, citation tracking (OpenAlex or Semantic Scholar) | Defined after M1 has run for 4 weeks |

### Non-goals for v1

- **Deployment:** Docker, AWS, Vercel, or any deployment beyond this Mac. A Dockerfile is about 15 lines when needed.
- **Other Workloads:** for example, simulation monitoring.
- **Sharing:** multi-user access, sharing, or a public site. Full texts are never served from anywhere, per the arXiv ToU.
- **Paper code:** reproducing paper results or running paper code.
- **Search:** full-text search across arXiv. Only harvested metadata and Carded sources are stored.
- **Training:** fine-tuning any model.

## 4. Domain scope

**Field:** physics-informed ML for lattice field theory and quantum many-body physics.

**Harvested OAI-PMH sets.** Cross-lists are included, and papers are deduplicated by arXiv ID.

| Set | Subject | Pre-filter (default) |
| --- | --- | --- |
| `physics:hep-lat` | Lattice field theory | none, all go to Filter |
| `physics:cond-mat:dis-nn` | Disordered systems and neural networks | none |
| `physics:cond-mat:str-el` | Strongly correlated electrons | none |
| `physics:quant-ph` | Quantum physics | keywords |
| `physics:cond-mat:stat-mech` | Statistical mechanics | keywords |
| `physics:physics:comp-ph` | Computational physics | keywords |
| `cs:cs:LG` | Machine learning | keywords, physics terms required |
| `stat:stat:ML` | Machine learning (stat) | keywords, physics terms required |

A Paper that appears in several sets gets the most permissive pre-filter of those sets.

**Research questions** are defined in `questions.yaml`, and each carries keywords and negative keywords:

1. **Generative sampling for lattice field theory:** flows and diffusion versus critical slowing down and topological freezing; scaling with volume and with gauge symmetry.
2. **Neural quantum states:** architectures that reach state-of-the-art ground-state energies or dynamics, compared with DMRG, tensor networks and QMC.
3. **Symmetry and physics constraints in architectures:** gauge equivariance and conservation laws, and what each buys in accuracy or sample efficiency.
4. **ML for observables and phases:** phase detection, and inverse problems such as spectral reconstruction.

**Out of scope (initial).** These are prose `scope_notes` in `questions.yaml`, applied by the Filter model; literal `negative_keywords` are for the code pre-filter only.
- "Renormalization" or "lattice" used only in an ML sense, with no physical system.
- Quantum-computing hardware, devices, or benchmarks of quantum processors.
- ML methods or benchmarks with no physics application.

**Seed papers.** These are the initial Golden set, as Placeholder Dev Papers:

- arXiv:1904.12072, Albergo, Kanwar and Shanahan (2019). This is the first end-to-end test case.
- arXiv:2003.06413, Kanwar et al. (2020)
- arXiv:1606.02318, Carleo and Troyer (2017)
- arXiv:1605.01735, Carrasquilla and Melko (2017)

## 5. Architecture

```
               launchd (06:00 daily + at login)
                         │
                   phy daily  ──────────────► $PHY_HOME/runs/<run_id>.jsonl (full request/response)
                         │                         ▲
   ┌───────────┬─────────┴──┬─────────────┐        │ Tracer
   ▼           ▼            ▼             ▼        │
 Watch  ──►  Filter  ──►   Read   ──►   Verify ────┘
 (OAI-PMH,   (pre-filter   (fetch src,  (code: verbatim
  no LLM)     + Haiku)      flatten,     quotes, invented
                            Sonnet)      numbers)
   │           │            │             │
   └───────────┴────► $PHY_HOME/phy.db (SQLite, WAL) ◄ phy ui (FastAPI + HTMX, localhost)
                              ▲                        ├─ /review     one Card at a time
                              │                        ├─ /monitor    Instrument tiles + funnel
                         phy eval ◄── golden/          └─ /runs        run list + viewer
```

### Components

**Runtime.** A single Python package, `phy`, run with `uv run phy <command>` from the repo. There are no long-running services except the UI, which runs only while the Reader uses it. Typer CLI; `cli.py` only parses arguments and calls plain Stage functions `run(ctx, …)`, where `ctx` carries config, db connection, Tracer and run_id.

**Installation home.** All instance state lives in `$PHY_HOME` (default `~/.phy-agent-platform`, overridden by the `PHY_HOME` env var), not in the repo, so the clone location doesn't matter. `config.py` resolves it once into a `Paths` object; no other module has path literals. See §6.

**Scheduling.** A launchd agent runs `phy daily`, which executes Watch → Filter → Read → Verify in order.
- Unattended runs execute a **Release**, never the dev clone, so half-finished code is never run at 06:00. A Release is an annotated tag `vMAJOR.MINOR.PATCH` on `main` that the Reader creates; phy never tags. The newest is `git tag --list 'v*' --sort=-v:refname`, ignoring pre-release tags. `phy schedule install` refuses when no Release exists; otherwise it checks the newest one out as a detached `git worktree` at `$PHY_HOME/app` (ignored by `$PHY_HOME/.gitignore`) and runs `uv sync` there.
- When a newer Release exists, the top bar of every UI page shows an amber "update available" badge listing the commits, `phy status` prints one line, and `phy daily` logs one INFO `schedule.update_available` event. It is never a red tile. The check is local: the worktree shares the dev repo's tags. `phy schedule update` takes `phy.lock`, refuses a downgrade, checks out the newest Release in the worktree and runs `uv sync`; migrations apply on the next connect.
- `phy schedule install` writes the plist with `StartCalendarInterval` at 06:00 plus `RunAtLoad`, the absolute path to `uv` (launchd's PATH is bare and it never reads shell profiles), `WorkingDirectory` set to `$PHY_HOME/app`, `PHY_HOME` in `EnvironmentVariables` (never a secret), and `StandardErrorPath` at `$PHY_HOME/logs/launchd.err` for crashes before logging starts.
- If the Mac was asleep at 06:00, the run starts on wake. Several missed slots collapse into one run.
- If the Mac was shut down, the run happens at login.
- A second run on the same day is harmless.
- A lock file (`$PHY_HOME/phy.lock`, `fcntl.flock`, released on process death so it never goes stale) is taken non-blocking by `daily` and by every Stage command, including `read --paper`. If it is held, the command logs and exits 0. `ui` and `status` never take it.

**Storage.** One SQLite file, `$PHY_HOME/phy.db`, in WAL mode with `busy_timeout`, accessed with raw `sqlite3` (no ORM) through named functions in `db.py`. Migrations are numbered `src/phy/migrations/NNN_<name>.sql` files tracked with `PRAGMA user_version` and applied automatically on connect; there are no down-migrations. The pipeline is the only bulk writer. The UI writes only short Review and Flag rows. Plain files hold everything humans author or diff (§6).

**Model calls.** All model calls go through one module (`phy.llm`). It is responsible for:
- building the request (prompt version, model, effort, cache breakpoints, `output_config.format` from the Pydantic schema);
- calling the API (sync in M0, Batch API optionally in M1);
- validating the response with `client.messages.parse()`;
- computing cost from `config.toml` prices;
- handing request and response to the Tracer.

**Tracer.** An interface with one method, `record(run, request, response, error)`. The v1 implementation writes a JSONL file per run and a summary row in `runs`. A Langfuse implementation can be added in M2 without touching any Stage.

**Logging.** structlog, with stdlib logging routed through it. Human-readable console lines go to stderr, and the same events go as JSON lines to `$PHY_HOME/logs/phy-YYYY-MM-DD.jsonl` (30 days kept).
- Event names are fixed `<area>.<past_tense>` strings (`read.card_written`, `arxiv.retry`). Variables go in keys; `run_id`, `stage`, `arxiv_id` and `version` are bound through contextvars.
- ERROR: a Stage run or paper failed and someone must look. WARNING: degraded but continuing. INFO: Stage start and finish with counts, one line per paper outcome; a normal `phy daily` stays under about 30 INFO lines. DEBUG: per request, only with `-v`.
- `httpx`, `httpcore`, `anthropic` and `urllib3` are capped at WARNING. Secrets, prompt and response bodies (the Tracer has those), abstracts and quote text are never logged. An exception is logged once, where it is handled.
- SQLite is the source of every pipeline metric, every Instrument tile and the budget guardrail. Logs carry only operational metrics (durations, retries, rate-limiter waits, lock contention), with the unit in the key (`duration_ms`, `wait_s`).

**arXiv access.** All arXiv traffic (OAI-PMH and `/src/`) goes through one rate limiter. It allows one request at a time, at least 3 s apart, coordinated across processes by a lock file (`$PHY_HOME/arxiv.lock`, blocking `flock`) holding the last request time. The request and any backoff sleeps happen while the lock is held. Retries use exponential backoff on 429, 503 and network errors, up to 3 attempts. After that the Stage run fails.

## 6. Files and data

```
phy-agent-platform/             # the repo: code only
├── GLOSSARY.md  QUICK_START.md
├── docs/SPEC.md  docs/adr/
├── prompts/<stage>/<version>.md  # immutable once used; config selects the active version
├── schemas/                    # exported Card JSON Schemas
├── src/phy/                    # cli, config, db, arxiv, watch, filter, read/, verify, eval,
│                               # card, questions, llm, tracer, locks, ui/, migrations/, defaults/
└── tests/                      # pytest; fixtures/ replayed with respx, -m live for the paid smoke test

$PHY_HOME/                      # ~/.phy-agent-platform by default; a local git repo, no remote
├── config.toml                 # all knobs (QUICK_START lists them)
├── questions.yaml              # research questions, keywords, negative keywords, scope notes
├── golden/
│   ├── manifest.yaml           # golden set version, papers, split, status, provenance
│   └── <arxiv_id>/reference.json
├── CHANGELOG.md                # accepted changes (Meta-work)
├── .gitignore                  # ignores everything below this line (arXiv ToU)
├── phy.db  phy.lock  arxiv.lock
├── app/                        # the installed Release: a detached git worktree of the repo
├── papers/<arxiv_id>v<n>/      # raw download + flattened.txt
├── golden_sources/<arxiv_id>v<n>/  # frozen, never re-fetched
├── runs/<run_id>.jsonl
└── logs/
```

`phy init` creates `$PHY_HOME`, seeds `config.toml` (the QUICK_START defaults), `questions.yaml` (the 4 questions of §4), an empty `golden/manifest.yaml` and `CHANGELOG.md` from `src/phy/defaults/`, never overwriting a file, and runs `git init` there. phy never commits: the Reader commits config, Golden and changelog changes as part of Meta-work. Config is read with `tomllib` and PyYAML into Pydantic models with `extra="forbid"`, once per command; invalid config fails the command before any work. `phy init` also makes one cheap API call to check auth and reports which credential source the SDK used.

The Card schema lives in `src/phy/card.py` as two Pydantic models. `CardDraft` is what the model writes: it is the single source for the API's `output_config.format` and for validating the response. `Card` is what is stored: `CardDraft` plus the fields Verify adds (Support, `loc`, `match_count`). The UI renders `Card`. Both JSON Schemas are exported to `schemas/` so diffs are visible.

### SQLite tables

| Table | One row per | Written by | Key columns |
| --- | --- | --- | --- |
| `papers` | Paper | Watch | arxiv_id (PK), latest_version, title, authors, abstract, categories, primary_category, license, sets, first_seen_at, updated_at |
| `paper_versions` | Paper version | Watch, Read | arxiv_id, version, submitted_at (from arXivRaw), first_seen_datestamp (OAI datestamp of the harvest that first carried this version), source_type (latex, pdf; detected by Read on download), local_path, sha256, fetched_at |
| `state` | key | Watch | `watch.hwm` (date), `watch.last_success_at` |
| `screenings` | Paper version | Filter | arxiv_id, version, prefilter (pass, fail, skipped), scores_json ({Q1..Q4: score, reason}), best_score, screened_in, model, prompt_version, run_id |
| `cards` | Card | Read, Verify | id, arxiv_id, version, card_json, status (draft, verified, reviewed, stale), unsupported_count, inferred_count, invented_numbers_json, warnings_json, model, prompt_version, schema_version, run_id |
| `reviews` | Review | UI | card_id, relevance (yes, partly, no), deep_read, seconds_spent, note, created_at |
| `flags` | Flag | UI | card_id, field_path, kind (wrong_value, quote_doesnt_support, missing, should_be_opinion), note, created_at |
| `runs` | Stage execution | every Stage | id, stage, arxiv_id, status, error, model, prompt_version, tokens_in, tokens_out, cache_read_tokens, cost_usd, started_at, ended_at, log_path |
| `eval_runs` | Golden eval run | `phy eval` | id, golden_version, split, prompt_versions_json, model, metrics_json, per_paper_json (each eval Card whole; eval Cards never go in `cards`), baseline_id, diff_json, material_changes, accepted_at, created_at |

Card fields are stored only inside `card_json` and queried with SQLite JSON functions. There is no separate `card_fields` table.

## 7. Stages

| Stage | Reads | Writes | Work | Acceptance check |
| --- | --- | --- | --- | --- |
| 1. Watch | OAI-PMH | papers, paper_versions, state | Plain Python | All sets harvested; high-water mark advanced |
| 2. Filter | Paper versions not yet screened | screenings | Pre-filter in code, then one `claude-haiku-5-5` call per Candidate scoring all 4 questions | Valid schema; precision ≥ 70% from Reviews |
| 3. Read | Screened-in and selected | paper_versions (source), cards | Fetch source, flatten, one `claude-sonnet-5-5` call returning a Card | Card validates against schema |
| 4. Verify | Draft Cards | cards (Support, status) | M0: code only. M1: adds a model reviewer | Unsupported fields ≤ 10%; zero invented numbers |

### 7.1 Watch

**Request.** For each set, Watch calls `ListRecords` with `metadataPrefix=arXivRaw`, `from=<hwm>`, and no `until`. It follows resumption tokens to the end within the same run. Tokens expire at the next UTC midnight and are never stored.

**Upserts and deduplication.**
- Papers are upserted on `arxiv_id`, and versions on (arxiv_id, version).
- The `arXivRaw` version history tells three cases apart: a new Paper, a new version, and a metadata-only change. Metadata-only changes update `papers` and create no work.

**Advancing the high-water mark.** The mark moves to the first page's `responseDate` (the earliest across sets, as a date), and only after all sets have completed. Otherwise it stays where it was, and the run fails; an expired resumption token fails it too, and the next run starts the set again from the mark.
- It never moves backwards. `phy watch --since DATE` re-harvests from `DATE`; it moves the mark only when `DATE` is on or before it, since a later `DATE` would leave a gap. `phy watch --reset` clears the mark, so that run backfills like a first run.
- Because OAI-PMH dates are whole days, the `from` day is always fetched again. That overlap is free, since upserts are idempotent.
- Watch never takes the mark from `Identify`, which can return a cached response.
- arXiv's CDN caches list responses for up to about 1 h (errors until UTC midnight), so a `responseDate` can be stale. It is never later than the data it covers, so the mark stays safe.
- OAI errors come back as HTTP 200 with an `<error code=…>` element. `noRecordsMatch` is an empty window, not a failure. Retries apply to HTTP 429, HTTP 503 and network errors.
- The client is hand-rolled with `httpx` and `lxml` (see the OAI-PMH client ticket in the M0 map). Tests replay recorded XML fixtures.

**First run.** With no mark yet, `from` is today minus `watch.backfill_days` (default 14).

**New versions of Carded Papers.** When a new version arrives for a Paper with a Card, that Card becomes Stale. It is queued for Read only if its Review rated it yes or partly.

**Watch saves metadata only.** Source is downloaded in Read.

### 7.2 Filter

**Pre-filter** (code). The pre-filter mode comes from the Paper's sets (§4).
- In `keywords` mode, the Paper passes when any question's keywords match its title or abstract and no negative keyword matches.
- `keywords+physics` additionally requires a physics term from `questions.yaml`.

A Paper that passes is a Candidate.

**Score** (model). One call per Candidate, with `effort` set to `filter.effort` (default `low`).
- The Filter prompt (`prompts/filter/<version>.md`, `system: self`) is the whole system prompt, with `{{questions}}` and `{{scope_notes}}` filled in; it is not the Read shared prompt. It carries the cache breakpoint, and with the output schema the cached prefix is about 1,350 tokens, above Haiku 5.5's 512-token minimum. The user turn is the title, arXiv categories and abstract (about 200–450 tokens).
- The output is one field per question id in `questions.yaml` (`{Q1..Qn: {reason, score}}`), a Pydantic model built from the ids, so adding a question changes no code. `reason` comes before `score` and is one line of at most 20 words.
- `score` is a float from 0 to 1, anchored in the prompt: **0.9+** the main contribution answers the question directly (always Carded); **0.7** on the topic but a narrower or neighbouring aspect; **0.5** something someone working on the question would use, though the focus is elsewhere (the bar for a Card); **0.3** same field or a shared technique, nothing new for the question; **0.1** shared words only. A paper under a scope note scores at most 0.3. Structured outputs can't enforce a numeric range, so code clamps to [0, 1] and logs a warning.
- Measured on the seed Papers plus six keyword-sharing probes (Filter prompt ticket in the M0 map): seeds scored 0.9–0.95 on their question, and every probe scored ≤ 0.3. A warm call costs about $0.00015 per Candidate (about 200 output tokens including thinking at `low`) and takes about 2 s.
- `best_score` is the maximum over questions. The Paper is Screened in when `best_score ≥ filter.threshold` (default 0.5).

### 7.3 Read

**Selection** runs at the start of each Read.
- Every Screened-in Paper with `best_score ≥ read.always_threshold` (default 0.9) is selected.
- Then the highest-scoring other Screened-in Papers are selected up to the day's quota. The quota is `read.daily_quota` (default 8) plus the unused quota carried over from earlier days in the same ISO week.
- Total Read volume per week never exceeds `read.weekly_ceiling` (default 50).
- Re-cards of Stale Papers count toward the quota.
- If the weekly spend guardrail (`budget.weekly_usd`) has been reached, nothing is selected and the Monitoring page says so.

**Fetching source.** Read fetches `arxiv.org/src/<id>v<n>` through the shared rate limiter and detects the format from magic bytes: gzip then tar, a single gzipped `.tex`, or a PDF.

**Flattening LaTeX.** Read uses a small stdlib flattener of our own, not pandoc or pylatexenc (see the LaTeX tooling ticket in the M0 map). It:
- finds the main file from the `00README` toplevel declaration, falling back to the uncommented `\documentclass` file;
- inlines `\input` and `\include` recursively, both braced and brace-less;
- strips `%` comments, `comment` environments, `\iffalse` blocks, and anything after `\end{document}`;
- drops the bibliography but keeps anything that follows it, such as appendices placed after it.

The result is `flattened.txt`: **raw flattened LaTeX**, never detexed (see the Quote format ticket in the M0 map). It is the text the model reads and quotes from, and the text Verify checks against.

**PDF fallback.** If there is no LaTeX source, text is extracted with `pypdfium2` into `flattened.txt`, and the Card records `source_type=pdf`.
- Soft hyphens (U+FFFE, U+00AD) are stripped, hyphenated line breaks joined and NFKC applied.
- Pages are separated by `\f`, and locations become page numbers.
- The model reads this text, never the PDF itself. PDF-sourced Cards have no key figures.

**The call.** One `claude-sonnet-5-5` call with `effort` set to `read.effort` (default `medium`). The output format is the Card schema.
- The prompt is ordered for caching: a short shared system prompt (`prompts/shared/<version>.md`), then the paper text with a cache breakpoint, then the Read instructions with the research questions filled in by the same `render_questions()` that Filter uses. M1's Verify reviewer reuses the same prefix, so it re-reads the paper from cache.
- Card text expands every acronym the first time it is used and names the authors as "Surname et al." (both surnames when there are two), never "the authors". The author list comes from the OAI-PMH metadata as a `{{authors}}` placeholder (Read prompt v2).
- List caps (for example ≤ 5 key results) are stated in the prompt but not enforced by the schema, because the API ignores `maxItems` and a paid call should not fail over one extra item. Verify trims an over-cap list and logs a warning.

**Prompt files.** Each `prompts/<stage>/<version>.md` starts with YAML front matter (`stage`, `version`, `system`, `model`, `effort`, `schema`, `params`, `notes`), followed by the body. Placeholders are `{{name}}`, never `$name`, because prompt text contains LaTeX `$`. A shared system prompt must stay byte-identical across every call that reuses its cached prefix.

### 7.4 Verify

**M0 code checks** (deterministic, free):

1. **Verbatim quotes.** One function, `canonicalise(text, source_type)`, is the matching contract for both source types. It runs identically on the quote and on `flattened.txt`, and a quote is found if canonical(quote) is a substring of canonical(source).
   - For LaTeX it removes `\cite`/`\citep`/`\citet`/`\ref`/`\eqref`/`\label` (with any `~` before them), maps `\% \& \$` to the plain characters, unwraps `\emph`/`\textit`/`\textbf`/`\text`, maps quotes and dashes to one form, maps `~ \, \ \;` to a space, and collapses whitespace.
   - Math is otherwise left as written, and matching is case-sensitive. Every rule has a unit test from a real seed-paper snippet.
   - It is built as a single pass that records the raw offset of every canonical character. `canonicalise_mapped()` returns the text plus that offset array, so `loc` maps a match back to the raw text exactly. Matching and locating share one code path.
   - A quote must be one contiguous span of 5–60 words, with no ellipses, that doesn't cross a paragraph or section boundary.

   **Every** quote on a Fact must be found and meet the shape rules, or the Fact is `unsupported`. There are no exceptions. A Fact with no Evidence is `unsupported`.
2. **Numbers.** A number is a token with an optional sign, digits with an optional decimal part, an optional `(d)` uncertainty and an optional exponent (`e-3`, `\times10^{-3}`, `×10⁻³`).
   - Digits glued to an identifier are not numbers: after a letter, `_`, `^` or `\` (`\phi^4`, `V^2`, `m_p`), or before a letter (`2D`), except for `%` and an `x`/`×` multiplier (`10x`). Numbers written as words are ignored.
   - One extractor runs on values, quotes and source, and numbers are compared as parsed values, never as substrings. Two numbers are equal when both the decimal value and the significant figures match: `1.2e-3` = `1.2\times10^{-3}` = `0.0012`, but `1.20` ≠ `1.2`. The sign is ignored. Error bars split into two numbers: `4.03(6)` and `4.03 \pm 0.06` both give `4.03` and `0.06`. Units are not checked, and conversions (`0.7` vs `70%`) don't match.
   - **Invented numbers (whole source):** every number in any Fact's value and in the `tldr` must appear in the canonicalised source. A miss makes that Fact `unsupported`, and the number goes into the Card's `invented_numbers`, which shows a red badge. The Card stays visible.
   - **Per field:** every number in a Fact's value must also appear in that Fact's own quotes. Otherwise a `supported` Fact becomes `inferred`, and the missing numbers are stored on it as `ungrounded_numbers` for the UI to highlight.
   - Support precedence is `unsupported` > `inferred` > `supported`: the model's `inferred: true` or any ungrounded number gives `inferred`.
3. **Locations are derived, not checked.** The model writes no Evidence `loc`. Verify computes it from the first match position.
   - It takes the innermost enclosing heading, as raw LaTeX: `Sec. "…"`, or `App. "…"` after `\appendix`. Detection covers `\section`, `\subsection`, `\subsubsection`, `\paragraph` (starred too), and preamble macros whose name or body contains `section`, such as `\ssection`. Inside `\begin{abstract}` it is `Abstract`, and before the first heading `front matter`.
   - It adds `· <label>` when the match is inside an `equation`, `align`, `gather`, `multline`, `eqnarray`, `figure` or `table` environment (starred too). On the PDF path it gives `p. N` instead, counted from `\f`.
   - Equation numbers are not computed. Verify also stores `match_count`.
4. **Labels.** These checks give warnings only and never change Support. A `key_equations` or `key_figures` label that doesn't exist in the source gives a warning, and the entry stays visible with a chip. A key equation's canonical `latex` must be a substring of its labelled environment's canonical body. A key figure's label must sit in a `figure` environment.
5. **List caps.** An over-cap list, including more than 2 Evidence quotes, keeps its first N, and an `over_cap` warning records the dropped count. The raw response stays in the run trace. Zero `key_results` gives a warning.

After these checks the Card's status becomes `verified`. Failures never get a status of their own. Verify stores `unsupported_count` (inferred fields excluded), `inferred_count`, `invented_numbers` (the red badge) and `warnings` (`{kind, field, detail}`, shown as grey chips on their sections).

**M1 model reviewer.** A separate prompt and a separate call that sees only one field's value, its quote, and the surrounding source passage. It never sees the Read reasoning. It answers whether the quote supports the value.

## 8. The Card

The Card is the product. Everything else exists to make Cards that are correct, grounded, and reviewable in 4 minutes.

```json
{
  "tldr": "Two sentences: what they did and the main result.",
  "key_results": [{"evidence": [{"quote": "...", "loc": "Sec. \"Results\" · fig:autocorr", "match_count": 1}], "value": "Integrated autocorrelation time reduced 10x at beta=6", "inferred": false, "support": "supported"}],
  "assumptions": [{"evidence": [...], "value": "...", "inferred": false, "support": "..."}],
  "system": {"evidence": [...], "value": "2D U(1) gauge theory, L=16..64", "inferred": false, "support": "..."},
  "method": {"evidence": [...], "value": "...", "inferred": true, "support": "inferred"},
  "baselines": {"evidence": [...], "value": "HMC, local Metropolis", "inferred": false, "support": "..."},
  "claimed_advance": {"evidence": [...], "value": "...", "inferred": false, "support": "..."},
  "limitations_stated": [{"evidence": [...], "value": "...", "support": "..."}],
  "key_equations": [{"label": "eq:autocorr", "latex": "...", "meaning": "..."}],
  "key_figures": [{"label": "fig:autocorr", "why": "one line"}],
  "code_data": null,
  "questions": [{"id": "Q1", "why": "one line"}],
  "opinion": {
    "limitations_flagged": [{"value": "agent opinion"}],
    "deep_read": {"recommend": true, "why": "one line"}
  }
}
```

Caps: `key_results` 1–5, `assumptions` ≤ 4, `limitations_stated` ≤ 4, `key_equations` ≤ 3, `key_figures` ≤ 3, `questions` ≤ 4, `limitations_flagged` ≤ 3, and 1–2 Evidence quotes per field.

**Rules:**
- Results keep their numbers, units and error bars exactly as the paper states them. No rounding.
- Field order is generation order. Inside a field the model writes its quotes first, then the value.
- Opinion fields are never mixed with the paper's own claims. They all live in the one `opinion` object, shown as "Agent's opinion".
- `baselines` and `code_data` are `null` when the paper has none. Null is not unsupported, and is not shaded.
- `inferred` is set by the model when the value follows from its quotes but isn't stated in them. Rewording alone is not inferred. Every number or parameter in a value must appear in that field's quotes, or the field is inferred.
- Quotes are copied character for character from `flattened.txt`, LaTeX included. Evidence `loc` and `match_count` are filled in by Verify, not by the model. `loc` is the section heading plus the enclosing `\label`, for LaTeX, or the page, for PDF.
- Key figures are chosen from captions (the model never sees pixels) and resolved by code to the `\includegraphics` file in the downloaded source.
- Every Card records its arXiv version, model, prompt version and schema version.

## 9. Review UI and Monitoring

`phy ui` serves FastAPI with HTMX on `127.0.0.1:8000`. It has no build step and no JavaScript framework.

### `/review`

Shows one Card at a time, ordered by `best_score`.
- **Layout:** one column in Card order: the tl;dr, results and assumptions come first, then setup, limitations, equations and figures, and the Agent's opinion as one dashed block. Each field is a row: the label with its support and number pills, the value, and a Flag button. Inferred fields are shaded blue and unsupported fields red. Evidence quotes are folded under each value and show the derived `loc`, plus "also appears N× elsewhere" when `match_count` > 1. A row of section pills under the top bar jumps between sections. Relevance, deep read and save sit in a bar fixed to the bottom. Quotes are raw LaTeX: math renders with KaTeX auto-render, fed the paper's preamble `\newcommand`s, and text markup is cleaned up server-side for display only. Key figures are shown from the source tarball: PNG and JPG as they are, PDF figures rendered to PNG with pypdfium2, and EPS as "figure not renderable". Stale and invented-number badges are shown.
- **Controls:** relevance (yes, partly, no), a Flag control on each field (a kind plus an optional note), and deep read (yes or no).
- **Keys:** `j`/`k` field, `[`/`]` section, `o` quotes, `f` Flag (then `1`–`4` for the kind, a note, Enter), `y`/`p`/`n` relevance, `d` deep read, `s` save, `r` raw LaTeX, `?` the key list.
- **Timing:** a server-side timer runs from render to submit, and the top bar shows a clock (amber at 4:00, red at 5:00). The next Card loads automatically.
- **Export:** an "Export to Markdown" button.

**Page conventions** for every page:
- **Top bar:** fixed to the top, with the nav, the page's subject (for `/review`: arXiv id, version, authors, title), status badges, and a row of section pills under it.
- **Hover help:** every badge, pill and control has hover text for a new user, kept in one shared dictionary so it reads the same everywhere.
- **Shared look:** support and status colours, HTMX for writes, `?` for keys.

### `/monitor`

Shows the Instrument tiles and the weekly funnel, with the page conventions (top bar with a red count, section pills, hover help).
- **Layout, top to bottom:** an action list, the funnel strip, then the tiles grouped under their question. The action list has one line per red tile: the Instrument, its value, its action from the table below and a link to the runs behind it; the name jumps to the tile. With nothing red it is one "All green" line.
- **Tile:** the name, the value, a sparkline of the last 7 days (one bar per day, weekends grey; Golden tiles show the last 7 eval runs instead), a note on what the value covers, the red rule and a "runs →" link. A tile is green, red, or grey when there is nothing to compute yet; grey says why ("no Reviews yet", "no Golden eval run yet", "baseline forming"). "Every M0 Instrument tile populated" means every tile has left grey.
- **Links:** "runs →" opens the run list, `/runs` filtered by query string (`stage`, `status`, `ids`, `since`). Golden tiles link to `/eval/<id>`, and the invented-numbers tile to the Card.
- **Windows:** the last 7 days, except Filter precision (14 days) and weekly spend (the ISO week from Monday 00:00 UTC, the window the guardrail enforces, shown with last week's total). Announcement days are Mon–Fri; arXiv holidays are ignored.
- **Queries:** every tile is one SQL query over the §6 tables, with no extra columns. Screenings and Cards are dated by their `run_id`'s `runs.started_at`. The unsupported rate divides by the fields that carry a Support, counted with `json_tree(card_json)`. The mark's date is the day it last advanced, since it moves to the run's `responseDate`. `runs.status` is `ok` or `failed`.

| Instrument | Question | Source | Red when | Action |
| --- | --- | --- | --- | --- |
| Papers harvested per announcement day | Is it running? | paper_versions, state | 0 on the latest announcement day the last successful Watch covered | Open the Watch run log |
| Days since the high-water mark advanced | Is it running? | state | > 2 announcement days | Check launchd and the last Watch run |
| Stage failures | Is it running? | runs | any failure in 7 days with no later `ok` run of the same Stage and paper | Open the run viewer |
| Candidates per week | Is the funnel shaped right? | screenings | outside `alerts.candidates_range` (not judged until Filter has run for 7 days) | Tighten or loosen keywords |
| Unsupported-field rate | Is it right? | cards | > 10% over 7 days | Inspect runs; revise the Read prompt or parser |
| Grounding rate (Golden) | Is it right? | eval_runs | < 98% on the latest eval run | Revert the change |
| Invented numbers | Is it right? | cards, eval_runs | any, on a Card from the last 7 days or the latest eval run | Inspect the Card; this is a hard fail on Golden |
| Golden run-to-run diff | Did a change move anything? | eval_runs | the latest eval run has a Material change on Dev and is not accepted | Review the diff on `/eval/<id>` before accepting |
| Filter precision | Is it useful? | reviews | yes or partly < 70% over 2 weeks (once ≥ 20 Reviews) | Add negative keywords or examples |
| Median review time | Is the Card well designed? | reviews | > 5 min | Shorten or reorder the Card |
| Cost per Carded paper | Is it affordable? | runs | median over papers (every run tied to the paper, retries included) > 2× the median of the 7 days from the first Card | Find which Stage grew |
| Weekly spend vs guardrail | Is it affordable? | runs | ≥ 80% of `budget.weekly_usd` | Check the volume; raise the limit deliberately |
| Reader minutes per relevant paper | Is it affordable? | reviews | > `alerts.minutes_per_relevant` (8) over 7 days | Find which grew: review time (trim the Card) or the share of "no" (tighten the Filter) |
| Minutes spent on "no" Cards | Is it affordable? | reviews | > `alerts.wasted_minutes` (40) over 7 days | Raise `filter.threshold` or add scope notes |

**Time is a cost too.** The two Reader-time tiles count only Review time, the one Reader activity M0 records. Reader minutes per relevant paper is `sum(seconds_spent)` over the Reviews rated yes or partly. Its note carries the **time multiplier**: relevant papers × `roi.baseline_minutes` ÷ Reader minutes, where the baseline is what getting the same out of a paper costs without the platform (abstract, introduction, figures, conclusions), not a full read. It is a note, not a red rule, because no single action follows from it. Minutes spent on "no" Cards is what the Filter's imprecision costs in the Reader's own time.

**Funnel:** harvested → Candidates → Screened in → Carded → verified → reviewed → relevant (yes or partly) → deep read, each step counting what happened in the last 7 days, with each step's % of the one before. Because these are activity counts, not a cohort, a step can exceed 100% (reviewing last week's Cards). A sudden narrowing between two steps points to the Stage to inspect.

### `/runs` and `/runs/<id>`

`/runs` lists runs, newest first, filtered by the query string the tiles link with. The run viewer renders one run's JSONL log: request (prompt version, model, and the prompt with the paper text collapsed), response, parsed output, validation errors, tokens, cache hits, and cost. This covers "why did it fail?" until Langfuse arrives.

**Alerts in M0** are red tiles only. M1 adds macOS notifications through `osascript` and a missed-papers log form.

## 10. Golden set and evaluation

The Golden set is the unit test suite for reading. It follows standard dataset practice.

**Versioning.** `golden/manifest.yaml` carries `version`. Any change to its membership, splits or Reference cards bumps the version. Scores are only compared within the same Golden set version.

**Splits.** A Paper is either Dev or Held-out.
- Dev Papers may be inspected and iterated on freely.
- Held-out Papers are scored only when a change is being accepted. Per-field results are hidden; only aggregates are shown.
- New Papers caught in review alternate between Dev and Held-out. The seed Papers are Dev.
- M0 has only Dev.

**Provenance.** Each entry records:
- why the Paper is in the set (seed, review mistake, out-of-scope probe, or awkward source);
- the pinned version and the sha256 of its frozen source;
- its status (Placeholder or Trusted);
- who corrected it and when.

**Frozen inputs.** Sources live in `$PHY_HOME/golden_sources/` and are never re-fetched. If the sha256 doesn't match, the eval fails before any model call.

**Placeholders.** In M0, up to 4 Placeholder Reference cards are drafted by the pipeline itself (`phy golden add`). They become Trusted once the Reader has corrected them field by field. For the seed Papers, the Reader writes their own card first and then compares, to avoid anchoring on the draft.

**Target composition by the end of week 4:** 20 Papers. That is 4 per question, 2 out-of-scope Papers that share keywords (testing Filter), and 2 with awkward source (heavy macros or PDF only), split between Dev and Held-out.

### Scores

| Score | Computed by | Applies to | Target | Milestone |
| --- | --- | --- | --- | --- |
| Grounding rate | Code: share of quotes found verbatim | all | ≥ 98% | M0 |
| Invented numbers | Code | all | 0, hard fail | M0 |
| Filter decision | Code: in-scope accepted, out-of-scope rejected | all | all correct | M0 |
| Run-to-run diff | Code: field-level diff against the baseline, split into Material changes and rewordings | Dev | Material changes reviewed by the Reader | M0 |
| Field accuracy | Model judge: correct, partial or wrong per field; the Reader audits 10% | Trusted | ≥ 90% | M1 |

**When it runs.** On every change to a prompt, model, schema or parser, and before that change becomes active. Once a week regardless, until the scores are stable. Every result is stored in `eval_runs` with the prompt versions, model and Golden set version.

**Accepting a change** is Meta-work. The Reader creates a new prompt version, runs `phy eval`, compares the results with the active version, and switches `config.toml` only if nothing regressed.

**The run-to-run diff.** A run's baseline is the latest accepted run with the same Golden set version; with none, the run shows "no baseline". `phy eval` stores the diff on the run and prints a summary (Scores against the baseline, Material changes and rewordings per Paper, a link); the full diff is on `/eval/<id>`, with the review page conventions.
- **Material change:** a field's Support changed, its set of parsed numbers changed (by value plus significant figures), an invented number appeared, a quote now fails, a list item was added or removed, `code_data` flipped between null and present, or a Filter decision crossed `filter.threshold` or `read.always_threshold`.
- **Rewording:** the value text changed with the same numbers and Support, different quotes still pass, or Filter scores drifted without crossing a threshold. Rewordings are shown greyed out and folded, never red. `loc` and `match_count` are ignored.
- List fields are paired between runs by content (shared numbers first, then text similarity), not position; reordering alone is ignored.
- Opinion field changes sit in their own folded section and never count; a deep-read recommendation flip is highlighted.
- Changed values are shown old over new, rendered with KaTeX, with a toggle to a word-level diff of the raw text.

**Accepting a run.** After switching `config.toml`, the Reader runs `phy eval accept <id>`. It refuses when the run's prompt versions and model differ from the active config, or when the run has a hard fail (an invented number, or grounding below 98%). There is no override. Accept never edits config.

## 11. Human loop and attention budget

| When | Activity | Time | Output |
| --- | --- | --- | --- |
| Mon–Fri mornings | Review about 6 Cards | 25 min/day | Reviews, Flags, deep-read picks |
| Monday | Glance at `/monitor`, act only on red tiles | 10 min | Fixes |
| Weekly | Pick 1–2 deep reads from deep_read=yes | 5 min | Deep-read list (the Digest replaces this in M2) |
| Weekend | Deep read 1–2 papers; from M1, one of them blind | 1–2 h | Notes attached to the Card |
| Friday | Spot-check 2 random Cards against their papers | 10 min | Flags |
| Monthly | Meta-work: trends, retire Instruments, add 2 Golden Papers, promote Placeholders | 2 h | Changelog entry |

Platform upkeep is capped at 30 min a week once v1 is stable.

## 12. Cost

Prices as of 2026-10 (they live in `config.toml`, so update them there):

| Model | Input ($/M tokens) | Output ($/M tokens) |
| --- | --- | --- |
| `claude-haiku-5-5` | $0.10 | $0.50 |
| `claude-sonnet-5-5` | $2.00 | $10.00 |

The Batch API halves both prices. Cache reads are discounted.

| Stage | Volume per week | Input each | Output each | Weekly cost (sync) |
| --- | --- | --- | --- | --- |
| Filter | about 250 Candidates (week 1 measures the real number) | about 2k tokens | 0.2k | about $0.08 |
| Read | ≤ 40 | about 80k (1904.12072 measured 27k) | 5k (measured 3k) | about $8.40 (1904.12072 measured $0.10 per Card) |
| Golden eval (4 Dev Papers) | per change | about 80k | 5k | about $0.85 per eval |
| Verify reviewer (M1) | ≤ 40 | about 60k, mostly cached | 3k | about $2 |

M0 costs roughly $10 a week, dominated by Read. M1's Batch switch roughly halves that.

**Filter is nearly free at Haiku 5.5 prices,** so the keyword pre-filter mainly reduces volume, not cost. Dropping it for more sets (`prefilter = "none"`) is a recall lever worth considering once week-1 volumes are known.

**Guardrails:**
- a monthly spend cap set in the Anthropic Console;
- `budget.weekly_usd`, after which Read selects nothing for the rest of the ISO week (Watch and Filter keep running).

## 13. Risks

| Risk | Likelihood | Impact | Mitigation |
| --- | --- | --- | --- |
| Subtly wrong Cards that the Reader trusts | Medium | High | Verbatim quote check, invented-number check, Golden set, spot-checks, shaded unsupported fields |
| Filter misses important papers | Medium | High | Permissive pre-filter on core sets, missed-papers log (M1), citation tracking (M2) |
| Silent harvesting gap (Mac off, arXiv change) | Medium | High | High-water mark with catch-up, `RunAtLoad`, "days since mark advanced" tile |
| LaTeX flattening breaks on odd submissions | High early on | Medium | PDF fallback, awkward-source Golden Papers, parse errors logged per run |
| Card review creeps past 5 min | High early on | Medium | Review-time Instrument; reorder or trim the Card |
| Golden set overfitting through Meta-work | Medium | Medium | Dev/Held-out split, hidden Held-out failures, versioned manifest |
| Reader's own reading skill erodes | Medium | High | Weekly blind deep read (M1) |
| Meta-work crowds out physics | Medium | Medium | 30-min upkeep cap; monthly learning check |
| arXiv rate limits or API changes | Low | Medium | Single shared rate limiter, backoff, heartbeat tile |
| Cost overrun | Low | Low | Console cap, weekly guardrail, Batch API |

## 14. Deferred decisions

- **How a Claim relates to a key result.** This is decided with Synthesize in M2.
- **The Improver agent's tool surface and approval flow.** This is decided in M2. It reads Flags, `runs` and `eval_runs`, writes new prompt versions, and runs `phy eval`. A human always switches the active version.
- **Embeddings for claims.** Candidates are `sqlite-vec` or brute force over a few thousand rows. Decided in M2.
- **Pre-filter `none` for all sets.** Revisited after week-1 volumes and the first missed-papers data.
- **Trust-discounted time multiplier.** A Card with a `wrong_value` Flag didn't save the Reader time, so the multiplier could discount Flagged Cards. Decided once Flag rates are known, in M1 or later.
- **`roi.baseline_minutes`.** The default of 15 is a guess. It is recalibrated by timing a few skims and deep reads.
