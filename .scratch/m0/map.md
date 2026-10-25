# Map: M0 — Cards on screen

Label: wayfinder:map

## Destination

Every M0 build decision is locked, and M0 (SPEC §3) is cut into ordered, vertical-slice implementation tickets, each buildable test-first in one agent session, ending in the M0 exit criteria. The spec has been reviewed and is ready to plan.

## Notes

- Sources of truth: `docs/SPEC.md`, `GLOSSARY.md`, `QUICK_START.md`, `docs/adr/`. Challenge any ticket answer that contradicts them, and update them when a ticket changes them.
- Every grilling session calls the Skill tool for `grilling` and `domain-modeling`. Prototype tickets use `prototype`, research tickets use `research`.
- Anything that touches the Claude API also loads `claude-api` (Python SDK, `output_config.format`, prompt caching).
- Standing preferences: simplest thing that runs unattended; native Python plus SQLite plus plain files; no Docker; idempotent, catch-up Stages; code checks before model checks.
- Tracker: local markdown. Tickets are in `issues/NN-<slug>.md`, with `Type:`, `Status:` and `Blocked by:` lines.

## Decisions so far

<!-- one line per resolved ticket: [title](issues/NN-slug.md): gist -->

- [OAI-PMH client: sickle or hand-rolled?](issues/03-oai-pmh-client.md): hand-rolled httpx + lxml (sickle is unmaintained and can't take our rate limiter); `from` is inclusive at UTC day level; errors come back as HTTP 200; the spec now records first_seen_datestamp instead of announced_date; fixtures are on branch `research/oai-pmh-client`.
- [LaTeX flattening and detex tooling](issues/02-latex-flattening-tooling.md): our own ~100-line stdlib flattener (pandoc, pylatexenc and arxiv_latex_cleaner rejected); pypdfium2 for PDFs; the research recommends raw LaTeX as the canonical text, which the quote format ticket decides.
- [Quote format: raw LaTeX or detexed prose?](issues/01-quote-format.md): quotes are raw flattened LaTeX (PDF → pypdfium2 text), matched through one shared `canonicalise()`; quotes are contiguous 5–60-word spans; Verify derives `loc` from the match instead of checking it; KaTeX renders quotes; a cheap caption-picked `key_figures` field is in M0.
- [Card schema v1 and Read prompt v1](issues/04-card-schema-and-read-prompt-prototype.md): `CardDraft` (model output, quotes before value) plus a stored `Card`; the model marks `inferred`; opinions sit in one `opinion` block; soft list caps; `{{name}}` prompt placeholders; Read stays at `medium` effort. One real call cost $0.098 (27k in, 3k out) and surfaced a per-field number-grounding gap, now a Verify check; the code is on branch `prototype/card-schema-read-prompt`.
- [Code checks in Verify](issues/06-verify-code-checks.md): numbers are parsed tokens (not glued to identifiers) compared by value plus significant figures, with the sign ignored and error bars split. The invented-number check covers every Fact plus the tl;dr; a miss makes the field unsupported and adds a red badge. A number missing from a field's own quotes makes it inferred. All quotes must pass. `canonicalise_mapped()` offsets give an exact `loc`. Status stays `verified`, with failures stored as `invented_numbers` and `warnings`.
- [Review page design](issues/05-review-page-prototype.md): one column in Card order (layout A) with section pills under a fixed top bar, quotes folded under each value, and a verdict bar fixed to the bottom; Flags are entered inline (`f`, `1`–`4`, note, Enter); keyboard shortcuts throughout; hover help everywhere from one shared dictionary; the top bar is the convention for every page; Read prompt v2 expands acronyms and names authors as "X et al."; the code is on branch `prototype/review-page`.
- [Code conventions and runtime plumbing](issues/07-code-conventions.md): all instance state (data plus `config.toml`, `questions.yaml`, `golden/`, `CHANGELOG.md`) lives in `$PHY_HOME` (default `~/.phy-agent-platform`, a local git repo phy never commits to); flat `src/phy/` modules; Typer; raw sqlite3 with `user_version` migrations; Pydantic config with `extra="forbid"`; structlog (readable stderr plus JSONL, SQLite first for metrics); pytest with respx and opt-in `-m live`; credentials via the SDK's own chain with `ant auth login` as default; `flock` locks; Python 3.13 and ruff.

## Not yet specified

_(nothing: the Monitoring page fog graduated into [Monitoring page layout and the SQL behind each tile](issues/11-monitoring-page.md))_

## Out of scope

M1 and M2 work: the model reviewer in Verify, the LLM accuracy judge, the Held-out split, the Batch API, macOS notifications, the missed-papers log, Synthesize, Digest, the Improver agent, Langfuse, and citation tracking.
