# /runs and the run viewer

Type: AFK
Status: done
Blocked by: 03, 06

## Goal

`/runs` lists Stage runs filtered by query string, and `/runs/<id>` shows exactly what a run sent and got back.

## Sources

SPEC §9 `/runs` and `/runs/<id>`, §5 Tracer; [Monitoring page layout and the SQL behind each tile](../../m0/issues/11-monitoring-page.md).

## Acceptance criteria

- `/runs`: newest first, filtered by `stage`, `status`, `ids` (comma-separated arXiv ids) and `since`; columns Stage, Paper, status, model, prompt version, tokens, cost, duration; with the page conventions.
- `/runs/<id>`: from the run's JSONL, the request (prompt version, model, the prompt with the paper text collapsed), response, parsed output, validation errors, tokens, cache hits and cost. A missing JSONL file says so instead of erroring.
- `status` filters and badges cover `ok`, `failed`, `skipped` (too long, from 20) and `aborted` (account blocked, from 21); `skipped` and `aborted` rows have no model call, so their viewer shows the `error` line only.
- Indexes `runs(started_at)` and `runs(stage, arxiv_id, started_at)` added in a migration, numbered with the next free number when built (see the README).

## Tests first

- Each filter on seeded `runs` rows, alone and combined.
- Viewer on a recorded Read trace: paper text collapsed, cost shown; on a failed run: error shown; missing log handled.

## Lift from

The `/runs` page in `origin/prototype/monitor-page:.scratch/m0/prototypes/monitor/app.py`, if present; otherwise the page conventions from 06.

## Not in this slice

Langfuse (M2).
