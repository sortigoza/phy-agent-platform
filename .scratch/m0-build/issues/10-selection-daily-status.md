# Read selection, phy daily and phy status

Type: AFK
Status: open
Blocked by: 05, 09

## Goal

`phy daily` runs Watch → Filter → Read → Verify unattended, with Read choosing what to Card within quota and budget, and `phy status` shows the state at a glance.

## Sources

SPEC §5 Scheduling (lock behaviour), §7.3 Selection, §12 Guardrails; QUICK_START §4.

## Acceptance criteria

- Selection: every Screened-in Paper version without a Card and with `best_score ≥ read.always_threshold`; then the highest-scoring others up to `read.daily_quota` plus the unused quota of earlier days in the same ISO week; never more than `read.weekly_ceiling` in the ISO week; Stale Cards whose Review was yes or partly are re-Carded and count toward the quota.
- Weekly guardrail: when the ISO week's `runs.cost_usd` reaches `budget.weekly_usd`, Read selects nothing and logs `read.budget_reached`; Watch and Filter still run.
- `phy read` (no `--paper`) runs selection then Read for each; one Paper failing doesn't stop the others.
- `phy daily` takes `phy.lock` once and runs the four Stages in order; a Stage failure is logged at ERROR and later Stages still run on what exists; exit code non-zero only for crashes. A normal run stays under about 30 INFO lines.
- `phy status` (no lock): high-water mark and last success, 7-day funnel counts, the ISO week's spend against the guardrail, unretried failures, and the Release line (from `release_status()`, still the stub until 11).

## Tests first

- Selection table tests: always-threshold over quota; carry-over Monday→Wednesday; weekly ceiling; Stale re-card counts; guardrail reached selects nothing.
- `daily` with all HTTP replayed: Stages run in order and each catches up; a second `daily` on the same day does nothing new.
- Lock held by another process → `daily` exits 0 having done nothing.
- `status` output on a seeded db.

## Lift from

The weekly-spend and funnel queries in `origin/prototype/monitor-page:.scratch/m0/prototypes/monitor/app.py` (`QUERIES`).

## Not in this slice

launchd (11), the tiles (16).
