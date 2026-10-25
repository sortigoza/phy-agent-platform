# Monitoring page layout and the SQL behind each tile

Type: prototype
Status: open
Blocked by: —

## Question

What does `/monitor` look like, and which SQL query feeds each M0 Instrument tile? Prototype the page with the review page conventions (top bar, section pills, hover help from the shared dictionary) against a seeded `phy.db` built from the SPEC §6 tables. For every M0 row in the SPEC §9 Instrument table, decide:
- the exact query (SQLite JSON functions over `card_json` where needed) and its time window;
- how the value, its red threshold (from `config.toml` `alerts.*`) and the link to the runs behind it are shown;
- what an empty or not-yet-computable tile shows, given the M0 exit criterion "every M0 Instrument tile populated".

Also settle the funnel view (harvested → pre-filtered → screened in → Carded → reviewed), and whether any tile needs a column or index the schema lacks.

## Context

Verify stores `unsupported_count`, `inferred_count`, `invented_numbers_json` and `warnings_json` per Card ([Code checks in Verify](06-verify-code-checks.md)). UI conventions: [Review page design](05-review-page-prototype.md). Database layer: raw `sqlite3`, and SQLite is the source of every tile; logs carry only operational metrics ([Code conventions and runtime plumbing](07-code-conventions.md)). The "Golden run-to-run diff" tile reads `eval_runs.material_changes` and `accepted_at`, and links to `/eval/<id>` ([How the Golden run-to-run diff is shown](10-golden-diff-display.md)).
