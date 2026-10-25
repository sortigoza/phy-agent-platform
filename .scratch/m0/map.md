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

## Not yet specified

- **How the Golden eval diff is shown** (CLI text or a UI page, and the granularity of a Card diff). This becomes clear once the Card shape from the Card schema prototype exists.
- **Monitoring page layout and the SQL behind each tile.** It depends on the UI patterns from the review page prototype and on the database layer chosen in the code conventions ticket.
- **Filter prompt v1 and its output schema.** It's small, but it should follow the prompt conventions the Card schema prototype sets.

## Out of scope

M1 and M2 work: the model reviewer in Verify, the LLM accuracy judge, the Held-out split, the Batch API, macOS notifications, the missed-papers log, Synthesize, Digest, the Improver agent, Langfuse, and citation tracking.
