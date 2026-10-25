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
- **Machine:** an Apple Silicon Mac with ≥ 16 GB RAM. Python 3.11+ managed by `uv`.
- **Model access:** the Anthropic Python SDK, with credentials from `ANTHROPIC_API_KEY` or `ant auth login`.
- **Source:** arXiv is the only source, harvested with OAI-PMH. LaTeX source is preferred and PDF is the fallback.

### Milestones

| Milestone | Delivers | Exit criteria |
| --- | --- | --- |
| **M0: Cards on screen** (target ≈ 1 week of building) | Watch (OAI-PMH, high-water mark), Filter, Read, Verify (code checks only), review UI, Monitoring page, run viewer, Golden eval on ≤ 4 Placeholder Dev Papers (code checks plus run-to-run diff), weekly spend guardrail, launchd schedule | First Card for arXiv:1904.12072 reviewed in the UI. 7 consecutive days of unattended runs with the high-water mark advancing. Every M0 Instrument tile populated. |
| **M1: Trust** | Model reviewer in Verify. Model-judged field accuracy on Trusted Papers. Held-out split. Missed-papers log. macOS notifications. "Deep read blind" toggle. Batch API switch. | ≥ 1 Trusted Golden Paper. Success criteria measurable. |
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

**Negative keywords (initial):** "renormalization" or "lattice" used only in an ML sense; pure quantum-computing hardware; pure ML benchmarks with no physics application.

**Seed papers.** These are the initial Golden set, as Placeholder Dev Papers:

- arXiv:1904.12072, Albergo, Kanwar and Shanahan (2019). This is the first end-to-end test case.
- arXiv:2003.06413, Kanwar et al. (2020)
- arXiv:1606.02318, Carleo and Troyer (2017)
- arXiv:1605.01735, Carrasquilla and Melko (2017)

## 5. Architecture

```
               launchd (06:00 daily + at login)
                         │
                   phy daily  ──────────────► data/runs/<run_id>.jsonl (full request/response)
                         │                         ▲
   ┌───────────┬─────────┴──┬─────────────┐        │ Tracer
   ▼           ▼            ▼             ▼        │
 Watch  ──►  Filter  ──►   Read   ──►   Verify ────┘
 (OAI-PMH,   (pre-filter   (fetch src,  (code: verbatim
  no LLM)     + Haiku)      flatten,     quotes, invented
                            Sonnet)      numbers)
   │           │            │             │
   └───────────┴────► data/phy.db (SQLite, WAL) ◄──── phy ui (FastAPI + HTMX, localhost)
                              ▲                        ├─ /review     one Card at a time
                              │                        ├─ /monitor    Instrument tiles + funnel
                         phy eval ◄── golden/          └─ /runs/<id>  run viewer
```

### Components

**Runtime.** A single Python package, `phy`, run with `uv run phy <command>`. There are no long-running services except the UI, which runs only while the Reader uses it.

**Scheduling.** A launchd agent runs `phy daily`, which executes Watch → Filter → Read → Verify in order.
- It is set up with `StartCalendarInterval` at 06:00 plus `RunAtLoad`.
- If the Mac was asleep at 06:00, the run starts on wake. Several missed slots collapse into one run.
- If the Mac was shut down, the run happens at login.
- A second run on the same day is harmless.
- A lock file (`data/phy.lock`) prevents two `daily` runs from overlapping.

**Storage.** One SQLite file, `data/phy.db`, in WAL mode with `busy_timeout`. The pipeline is the only bulk writer. The UI writes only short Review and Flag rows. Plain files hold everything humans author or diff (§6).

**Model calls.** All model calls go through one module (`phy.llm`). It is responsible for:
- building the request (prompt version, model, effort, cache breakpoints, `output_config.format` from the Pydantic schema);
- calling the API (sync in M0, Batch API optionally in M1);
- validating the response with `client.messages.parse()`;
- computing cost from `config.toml` prices;
- handing request and response to the Tracer.

**Tracer.** An interface with one method, `record(run, request, response, error)`. The v1 implementation writes a JSONL file per run and a summary row in `runs`. A Langfuse implementation can be added in M2 without touching any Stage.

**arXiv access.** All arXiv traffic (OAI-PMH and `/src/`) goes through one rate limiter. It allows one request at a time, at least 3 s apart, coordinated across processes by a lock file holding the last request time. Retries use exponential backoff on 429, 503 and network errors, up to 3 attempts. After that the Stage run fails.

## 6. Files and data

```
phy-agent-platform/
├── GLOSSARY.md  QUICK_START.md
├── docs/SPEC.md  docs/adr/
├── config.toml                 # all knobs (QUICK_START lists them)
├── questions.yaml              # research questions, keywords, negative keywords
├── prompts/<stage>/<version>.md  # immutable once used; config selects the active version
├── golden/
│   ├── manifest.yaml           # golden set version, papers, split, status, provenance
│   └── <arxiv_id>/reference.json
├── ops/launchd/phy.daily.plist
├── src/phy/                    # watch, filter, read, verify, eval, llm, tracer, db, ui
└── data/                       # gitignored, local only (arXiv ToU)
    ├── phy.db
    ├── papers/<arxiv_id>v<n>/  # raw download + flattened.txt
    ├── golden_sources/<arxiv_id>v<n>/  # frozen, never re-fetched
    └── runs/<run_id>.jsonl
```

The Card schema is a Pydantic model in `src/phy/card.py`. It is the single source for the API's `output_config.format`, for validation, and for the UI. Its JSON Schema is exported to `schemas/card.schema.json` so diffs are visible.

### SQLite tables

| Table | One row per | Written by | Key columns |
| --- | --- | --- | --- |
| `papers` | Paper | Watch | arxiv_id (PK), latest_version, title, authors, abstract, categories, primary_category, license, sets, first_seen_at, updated_at |
| `paper_versions` | Paper version | Watch, Read | arxiv_id, version, announced_date, source_type (latex, pdf), local_path, sha256, fetched_at |
| `state` | key | Watch | `watch.hwm` (date), `watch.last_success_at` |
| `screenings` | Paper version | Filter | arxiv_id, version, prefilter (pass, fail, skipped), scores_json ({Q1..Q4: score, reason}), best_score, screened_in, model, prompt_version, run_id |
| `cards` | Card | Read, Verify | id, arxiv_id, version, card_json, status (draft, verified, reviewed, stale), unsupported_count, model, prompt_version, schema_version, run_id |
| `reviews` | Review | UI | card_id, relevance (yes, partly, no), deep_read, seconds_spent, note, created_at |
| `flags` | Flag | UI | card_id, field_path, kind (wrong_value, quote_doesnt_support, missing, should_be_opinion), note, created_at |
| `runs` | Stage execution | every Stage | id, stage, arxiv_id, status, error, model, prompt_version, tokens_in, tokens_out, cache_read_tokens, cost_usd, started_at, ended_at, log_path |
| `eval_runs` | Golden eval run | `phy eval` | id, golden_version, split, prompt_versions_json, model, metrics_json, per_paper_json, created_at |

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

**Advancing the high-water mark.** The mark moves to the first page's `responseDate`, and only after all sets have completed. Otherwise it stays where it was.
- Because OAI-PMH dates are whole days, the `from` day is always fetched again. That overlap is free, since upserts are idempotent.
- Watch never takes the mark from `Identify`, which can return a cached response.

**First run.** With no mark yet, `from` is today minus `watch.backfill_days` (default 14).

**New versions of Carded Papers.** When a new version arrives for a Paper with a Card, that Card becomes Stale. It is queued for Read only if its Review rated it yes or partly.

**Watch saves metadata only.** Source is downloaded in Read.

### 7.2 Filter

**Pre-filter** (code). The pre-filter mode comes from the Paper's sets (§4).
- In `keywords` mode, the Paper passes when any question's keywords match its title or abstract and no negative keyword matches.
- `keywords+physics` additionally requires a physics term from `questions.yaml`.

A Paper that passes is a Candidate.

**Score** (model). One call per Candidate, with `effort` set to `filter.effort` (default `low`).
- The system prompt and the question definitions form a stable cached prefix. The title and abstract come after the cache breakpoint.
- The output is `{Q1..Q4: {score: 0–1, reason: one line}}`.
- `best_score` is the maximum over questions. The Paper is Screened in when `best_score ≥ filter.threshold` (default 0.5).

### 7.3 Read

**Selection** runs at the start of each Read.
- Every Screened-in Paper with `best_score ≥ read.always_threshold` (default 0.9) is selected.
- Then the highest-scoring other Screened-in Papers are selected up to the day's quota. The quota is `read.daily_quota` (default 8) plus the unused quota carried over from earlier days in the same ISO week.
- Total Read volume per week never exceeds `read.weekly_ceiling` (default 50).
- Re-cards of Stale Papers count toward the quota.
- If the weekly spend guardrail (`budget.weekly_usd`) has been reached, nothing is selected and the Monitoring page says so.

**Fetching source.** Read fetches `arxiv.org/src/<id>v<n>` through the shared rate limiter and detects the format from magic bytes: gzip then tar, a single gzipped `.tex`, or a PDF.

**Flattening LaTeX.**
- Find the main file (the one containing `\documentclass`).
- Inline `\input` and `\include` recursively, and strip comments.
- Keep the appendices and drop the bibliography.

The result is `flattened.txt`. It is the text the model reads and the text Verify checks against.

**PDF fallback.** If there is no LaTeX source, text is extracted from the PDF, and the Card records `source_type=pdf`. Locations then become page numbers.

**The call.** One `claude-sonnet-5-5` call with `effort` set to `read.effort` (default `medium`). The output format is the Card schema.
- The prompt is ordered for caching: a short shared system prompt, then the paper text with a cache breakpoint, then the Read instructions. M1's Verify reviewer reuses the same prefix, so it re-reads the paper from cache.

### 7.4 Verify

**M0 code checks** (deterministic, free):

1. **Verbatim quotes.** Each Evidence quote is matched against `flattened.txt` after normalising whitespace, Unicode quotes and dashes, and LaTeX spacing commands such as `~`, `\,` and `\ `. If a quote is not found, the field is `unsupported`. There are no exceptions.
2. **Invented numbers.** Every number in `key_results` values must appear in the source text, with tolerant formatting (for example `1.2\times10^{-3}` matches `1.2e-3`). Any miss is a hard failure for that Card. The Card stays visible but carries a red badge.
3. **Locations.** Each `loc` must name a section or equation that exists in the source. A failure produces a warning, not a change of Support.

After these checks the Card's status becomes `verified`, and `unsupported_count` is stored.

**M1 model reviewer.** A separate prompt and a separate call that sees only one field's value, its quote, and the surrounding source passage. It never sees the Read reasoning. It answers whether the quote supports the value.

## 8. The Card

The Card is the product. Everything else exists to make Cards that are correct, grounded, and reviewable in 4 minutes.

```json
{
  "tldr": "Two sentences: what they did and the main result.",
  "questions": [{"id": "Q1", "why": "one line"}],
  "system": {"value": "2D U(1) gauge theory, L=16..64", "evidence": [{"quote": "...", "loc": "Sec. 2"}], "support": "supported"},
  "method": {"value": "...", "evidence": [...], "support": "..."},
  "baselines": {"value": "HMC, local Metropolis", "evidence": [...], "support": "..."},
  "key_results": [{"value": "Integrated autocorrelation time reduced 10x at beta=6", "evidence": [...], "support": "..."}],
  "claimed_advance": {"value": "...", "evidence": [...], "support": "..."},
  "assumptions": [{"value": "...", "evidence": [...], "support": "..."}],
  "key_equations": [{"latex": "...", "meaning": "...", "loc": "Eq. (7)"}],
  "limitations_stated": [{"value": "...", "evidence": [...]}],
  "limitations_flagged": [{"value": "agent opinion, labelled as such"}],
  "code_data": {"value": "GitHub link or none", "evidence": [...]},
  "deep_read": {"recommend": true, "why": "one line"}
}
```

**Rules:**
- Results keep their numbers, units and error bars exactly as the paper states them. No rounding.
- Opinion fields are never mixed with the paper's own claims.
- Locations are sections and equation numbers for LaTeX, and pages for PDF.
- Every Card records its arXiv version, model, prompt version and schema version.

## 9. Review UI and Monitoring

`phy ui` serves FastAPI with HTMX on `127.0.0.1:8000`. It has no build step and no JavaScript framework.

### `/review`

Shows one Card at a time, ordered by `best_score`.
- **Layout:** the tl;dr, results and assumptions come first. Unsupported fields are shaded, and Evidence quotes expand on click. Stale and invented-number badges are shown.
- **Controls:** relevance (yes, partly, no), a Flag control on each field (a kind plus an optional note), and deep read (yes or no).
- **Timing:** a server-side timer runs from render to submit. The next Card loads automatically.
- **Export:** an "Export to Markdown" button.

### `/monitor`

Shows the Instrument tiles (green or red, with a one-week sparkline) and the weekly funnel. Every red tile links to the runs that caused it.

| Instrument | Question | Source | Red when | Action |
| --- | --- | --- | --- | --- |
| Papers harvested per announcement day | Is it running? | papers | 0 on an announcement day | Open the Watch run log |
| Days since the high-water mark advanced | Is it running? | state | > 2 announcement days | Check launchd and the last Watch run |
| Stage failures | Is it running? | runs | any unretried failure | Open the run viewer |
| Candidates per week | Is the funnel shaped right? | screenings | outside `alerts.candidates_range` | Tighten or loosen keywords |
| Unsupported-field rate | Is it right? | cards | > 10% over 7 days | Inspect runs; revise the Read prompt or parser |
| Grounding rate (Golden) | Is it right? | eval_runs | < 98% | Revert the change |
| Invented numbers | Is it right? | cards, eval_runs | any | Inspect the Card; this is a hard fail on Golden |
| Golden run-to-run diff | Did a change move anything? | eval_runs | any field changed on Dev | Review the diff before accepting |
| Filter precision | Is it useful? | reviews | < 70% over 2 weeks (once ≥ 20 Reviews) | Add negative keywords or examples |
| Median review time | Is the Card well designed? | reviews | > 5 min | Shorten or reorder the Card |
| Cost per Carded paper | Is it affordable? | runs | > 2× the week-1 median | Find which Stage grew |
| Weekly spend vs guardrail | Is it affordable? | runs | ≥ 80% of `budget.weekly_usd` | Check the volume; raise the limit deliberately |

**Funnel:** harvested → Candidates → Screened in → Carded → verified → reviewed → relevant → deep read. A sudden narrowing between two steps points to the Stage to inspect.

### `/runs/<id>`

The run viewer renders one run's JSONL log: request (prompt version, model, and the prompt with the paper text collapsed), response, parsed output, validation errors, tokens, cache hits, and cost. This covers "why did it fail?" until Langfuse arrives.

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

**Frozen inputs.** Sources live in `data/golden_sources/` and are never re-fetched. If the sha256 doesn't match, the eval fails before any model call.

**Placeholders.** In M0, up to 4 Placeholder Reference cards are drafted by the pipeline itself (`phy golden add`). They become Trusted once the Reader has corrected them field by field. For the seed Papers, the Reader writes their own card first and then compares, to avoid anchoring on the draft.

**Target composition by the end of week 4:** 20 Papers. That is 4 per question, 2 out-of-scope Papers that share keywords (testing Filter), and 2 with awkward source (heavy macros or PDF only), split between Dev and Held-out.

### Scores

| Score | Computed by | Applies to | Target | Milestone |
| --- | --- | --- | --- | --- |
| Grounding rate | Code: share of quotes found verbatim | all | ≥ 98% | M0 |
| Invented numbers | Code | all | 0, hard fail | M0 |
| Filter decision | Code: in-scope accepted, out-of-scope rejected | all | all correct | M0 |
| Run-to-run diff | Code: field-level diff against the last accepted run | Dev | Reviewed by the Reader | M0 |
| Field accuracy | Model judge: correct, partial or wrong per field; the Reader audits 10% | Trusted | ≥ 90% | M1 |

**When it runs.** On every change to a prompt, model, schema or parser, and before that change becomes active. Once a week regardless, until the scores are stable. Every result is stored in `eval_runs` with the prompt versions, model and Golden set version.

**Accepting a change** is Meta-work. The Reader creates a new prompt version, runs `phy eval`, compares the results with the active version, and switches `config.toml` only if nothing regressed.

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
| Read | ≤ 40 | about 80k | 5k | about $8.40 |
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
