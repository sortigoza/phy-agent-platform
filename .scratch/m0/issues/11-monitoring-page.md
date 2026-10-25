# Monitoring page layout and the SQL behind each tile

Type: prototype
Status: resolved
Blocked by: —
Assignee: Saul

## Question

What does `/monitor` look like, and which SQL query feeds each M0 Instrument tile? Prototype the page with the review page conventions (top bar, section pills, hover help from the shared dictionary) against a seeded `phy.db` built from the SPEC §6 tables. For every M0 row in the SPEC §9 Instrument table, decide:
- the exact query (SQLite JSON functions over `card_json` where needed) and its time window;
- how the value, its red threshold (from `config.toml` `alerts.*`) and the link to the runs behind it are shown;
- what an empty or not-yet-computable tile shows, given the M0 exit criterion "every M0 Instrument tile populated".

Also settle the funnel view (harvested → pre-filtered → screened in → Carded → reviewed), and whether any tile needs a column or index the schema lacks.

## Context

Verify stores `unsupported_count`, `inferred_count`, `invented_numbers_json` and `warnings_json` per Card ([Code checks in Verify](06-verify-code-checks.md)). UI conventions: [Review page design](05-review-page-prototype.md). Database layer: raw `sqlite3`, and SQLite is the source of every tile; logs carry only operational metrics ([Code conventions and runtime plumbing](07-code-conventions.md)). The "Golden run-to-run diff" tile reads `eval_runs.material_changes` and `accepted_at`, and links to `/eval/<id>` ([How the Golden run-to-run diff is shown](10-golden-diff-display.md)).

## Answer

**Layout: tile wall with an action list on top** (prototype variant D, the Reader's pick: A's tiles plus C's red-tile actions, made compact). Top to bottom:
1. **Action list.** One line per red tile: the Instrument, its value, its SPEC action and "runs →"; the name jumps to the tile. With nothing red, one "All green" line. C's full-size action cards were tried first and pushed the tiles below the fold with 8 reds, so each became one line.
2. **Funnel strip.** Eight steps with counts and each step's % of the one before.
3. **Tiles grouped under their question**, with section pills for "Needs action", "Funnel" and each question. A tile shows the name, value, 7-day sparkline (weekends grey; Golden tiles plot the last 7 eval runs), a note on what the value covers, the red rule and "runs →".

**Empty tiles are grey**, neither green nor red, and say why ("no Reviews yet", "no Golden eval run yet: run phy eval", "baseline forming: week 1 not over", Candidates "partial week: not judged yet"). The M0 exit criterion "every M0 Instrument tile populated" means every tile has left grey. In the `fresh` scenario (day 2), four tiles were grey.

**SQL.** Every tile is one query over the SPEC §6 tables, and no column or table had to be added:
- Screenings and Cards are dated through `run_id` → `runs.started_at`.
- The unsupported rate is `sum(unsupported_count)` over the count of `support` keys in `json_tree(card_json)`.
- The mark's date is the day it last advanced, because it moves to the run's `responseDate`. Days since the mark advanced counts the Mon–Fri days after it, with a recursive CTE.
- Medians use `row_number()` over the middle row(s), because SQLite has no median.
- Two indexes help: `runs(started_at)` and `runs(stage, arxiv_id, started_at)` for the unretried-failure `NOT EXISTS`.
The exact queries are in `QUERIES` in the prototype (`q` shows them on the page).

**Decisions:**
- **Windows:** the last 7 days, except Filter precision (14 days) and weekly spend (the ISO week, which is what the guardrail enforces, shown with last week's total so a Monday glance isn't empty; the Reader did not object to this default).
- **Funnel:** activity counts in the last 7 days, not a cohort; a step can exceed 100%.
- **Filter precision:** yes and partly both count as relevant, like the Stale re-card rule.
- **Stage failures:** a failure is unretried when no later `ok` run of the same Stage (and paper) exists; it is red for 7 days, then drops off.
- **Papers harvested:** red only at 0 on the latest announcement day the last successful Watch covered. A stuck Watch is the mark tile's job; the harvested tile shows the stale day in its note.
- **Cost per Carded paper:** the median over papers of every run tied to the paper (retries included); the baseline is the same median over the 7 days from the first Card, and the tile stays without a red rule until then. Its note splits the 7-day spend by Stage.
- **Announcement days** are Mon–Fri; arXiv holidays are ignored (a false red about once a year).
- **Golden run-to-run diff** reads only the latest eval run; with no baseline it is grey ("accept it to make the baseline").
- **New in the SPEC:** `runs.status` is `ok` or `failed`, and a `/runs` list page, filtered by query string (`stage`, `status`, `ids`, `since`), is what every "runs →" link opens.

**Observed in the `broken` scenario:** one stuck Watch turned three tiles red (days since the mark, Stage failures, Candidates). The action list makes that cascade readable as one block.

**Spec changes made:** SPEC §9 `/monitor` (layout, tile anatomy, windows, queries, sharpened red rules, funnel) and `/runs`; the §5 diagram.

**Assets:** branch `prototype/monitor-page` (commit `06e82ed`, never merged, pushed to `origin`); the code is in `.scratch/m0/prototypes/monitor/` (`.venv/bin/python app.py`, `/monitor?variant=A|B|C|D&scenario=healthy|broken|fresh`).
