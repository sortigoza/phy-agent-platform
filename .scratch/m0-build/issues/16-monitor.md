# /monitor

Type: AFK
Status: open
Blocked by: 07, 10, 12, 15

## Goal

`/monitor` shows every M0 Instrument tile, the funnel and the action list, each tile one SQL query over the SPEC §6 tables.

## Sources

SPEC §9 `/monitor` (layout, tile, links, windows, queries, the Instrument table, time is a cost, funnel); [Monitoring page layout and the SQL behind each tile](../../m0/issues/11-monitoring-page.md).

## Acceptance criteria

- The 14 Instruments of SPEC §9, each a named query in one module, with its window, red rule from `config.toml` `alerts.*`, note, "runs →" link (`/runs?…`, Golden tiles to `/eval/<id>`, invented numbers to the Card) and grey reason when there is nothing to compute.
- Layout: action list (one line per red tile, or "All green"), funnel strip (eight steps, 7-day activity counts, % of previous), tiles grouped under their question with section pills; top bar with the red count.
- 7-day sparklines, weekends grey; Golden tiles plot the last 7 eval runs.
- The time multiplier in the Reader-minutes tile's note.
- No new columns; any new index goes in a migration.

## Tests first

- One test per tile on seeded data: green, red and grey cases, matching SPEC's red rules (including "not judged until Filter has run 7 days", "once ≥ 20 Reviews", the cost baseline).
- Funnel counts on a seeded week.
- Every hover key exists in the dictionary.

## Lift from

`origin/prototype/monitor-page:.scratch/m0/prototypes/monitor/app.py` — `QUERIES` and variant D's templates.

## Not in this slice

M1's attention-budget tile and notifications.
