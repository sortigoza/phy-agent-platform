# M0 build: Cards on screen

Implementation tickets for M0 (SPEC §3), cut by the map ticket [Slice M0 into implementation tickets](../m0/issues/08-slice-m0.md). Each is one test-first agent session. Work them in the order of the table below (not strictly by number, since 18–22 were added by [Amend the M0 cut](../m0/issues/20-amend-m0-cut.md)); `Blocked by:` names the tickets that must be done first.

Ticket format: `Type: AFK|HITL`, `Status: open|in-progress|done`, `Blocked by:`, `Assignee:` once claimed. Sections: Goal, Sources, Acceptance criteria, Tests first, Lift from, Not in this slice.

Rules for every ticket:
- **Tests first.** Write the failing tests listed, then the code. pytest; respx replays HTTP for OAI-PMH, arXiv `/src/` and the Anthropic SDK; an autouse fixture sets `PHY_HOME=tmp_path`; no network unless `-m live`.
- **Lift, don't copy blindly.** Prototype code on the `prototype/*` and `research/*` branches is a reference implementation. Port it under the tests, into the flat `src/phy/` layout and conventions of [Code conventions and runtime plumbing](../m0/issues/07-code-conventions.md). Read files with `git show origin/<branch>:<path>`.
- **No arXiv source in git** (the repo is public). LaTeX tests use synthetic `.tex` snippets written by hand to mimic the seed papers.
- **Migrations.** A slice adds `src/phy/migrations/NNN_<name>.sql` for the tables it introduces, numbered with the next free number when it's built (never `004`, which was skipped; filling it would be ignored by any db already past it). A merged migration is never edited.
- **Docs move with code.** If a slice changes behaviour SPEC, QUICK_START or GLOSSARY describe, update them in the same commit.

| # | Slice | Blocked by |
| --- | --- | --- |
| 01 | [Skeleton and phy init](issues/01-skeleton-and-init.md) | — |
| 02 | [Source to flattened text](issues/02-source-to-flattened-text.md) | 01 |
| 03 | [The Read call](issues/03-read-call.md) | 02 |
| 04 | [Verify: quotes and locations](issues/04-verify-quotes-and-loc.md) | 03 |
| 05 | [Verify: numbers, labels and caps](issues/05-verify-numbers-labels-caps.md) | 04 |
| 06 | [/review: render a Card](issues/06-review-render.md) | 05 |
| 07 | [/review: Reviews and Flags](issues/07-review-writes.md) | 06 |
| 08 | [Watch](issues/08-watch.md) | 02 |
| 09 | [Filter](issues/09-filter.md) | 03, 08 |
| 10 | [Read selection, phy daily and phy status](issues/10-selection-daily-status.md) | 05, 09 |
| 11 | [Schedule and Releases](issues/11-schedule-and-releases.md) | 10 |
| 13 | [Golden set](issues/13-golden-set.md) | 03 |
| 19 | [Read selection and the predictive guardrail](issues/19-selection-and-guardrail.md) | 11 |
| 20 | [Per-Card limits: no caching, output and input caps](issues/20-per-card-limits.md) | 19 |
| | **Release `v0.2.0`** | 20 |
| 18 | [Verify: quote rules from the first real Cards](issues/18-verify-quote-rules.md) | 20 |
| 21 | [Read and Filter failure bookkeeping](issues/21-failure-bookkeeping.md) | 18 |
| 22 | [Logging and schedule hygiene](issues/22-logging-and-schedule-hygiene.md) | 21 |
| | **Release `v0.3.0`** | 22 |
| 12 | [/runs and the run viewer](issues/12-runs-viewer.md) | 03, 06 (any time) |
| 14 | [phy eval scores](issues/14-eval-scores.md) | 05, 09, 13, 22 |
| 15 | [Run-to-run diff and eval accept](issues/15-run-to-run-diff.md) | 06, 14 |
| 16 | [/monitor](issues/16-monitor.md) | 07, 10, 12, 15 |
| 17 | [M0 burn-in](issues/17-burn-in.md) | 11, 16, 18–22 |

**Milestones inside the cut.** After 07, the first M0 exit criterion can be met (first Card for 1904.12072 reviewed in the UI); it hasn't been yet, see 17's checklist. After 11, `v0.1.0` was tagged and the first scheduled run overspent ([post-mortem](postmortems/2026-10-26-first-scheduled-run.md)); the schedule is off until the Reader re-installs it under the config guard, and the 7-day clock of 17 starts then. After 20, tag `v0.2.0` (spend protection in code); after 22, tag `v0.3.0` (quote rules, failure bookkeeping, logging). After 16 and 7 clean days, M0 is done.
