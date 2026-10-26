# Restart the burn-in now, on a config-only spend guard?

Type: grilling
Status: resolved
Blocked by: —
Assignee: Saul
Assignee: Saul

## Question

The schedule is off until post-mortem fixes 1–3 land. The 7-day burn-in clock (build ticket [M0 burn-in](../../m0-build/issues/17-burn-in.md)) only needs Watch to advance the mark, and every day the schedule is off delays M0. Should the schedule go back on **now**, before any code fix, guarded by config alone?

Points to settle:
- **The guard.** Read picks nothing until Monday 2026-11-02, because `weekly_ceiling` is used up. After that, `always` picks are uncapped per run. Is one of these enough until the code fixes ship?
  - raise `read.always_threshold` past every possible score, so `daily_quota` (8) is the only per-run cap;
  - `0.95`, as the post-mortem proposes;
  - a lower `weekly_ceiling` or `budget.weekly_usd`.
- **The deadline.** If the guard is config only, do the code fixes have to ship as a Release before 2026-11-02 00:00 UTC, or does the guard hold indefinitely?
- **The account (ops).** Top up the credit above `budget.weekly_usd` and set a Console spend cap, before re-enabling or after? Without credit, Filter fails too.
- **The clock.** Does a day with Watch `ok` but Read empty, or Read failed, count toward the 7 days? Build ticket 17 counts only the mark advancing.

The resolution updates build ticket 17's checklist with the date the clock restarts.

## Context

- [First scheduled run post-mortem](../../m0-build/postmortems/2026-10-26-first-scheduled-run.md), "Before re-enabling the schedule".
- `plan()` takes every Candidate at or over `always_threshold`; `daily_quota` limits only the extra picks.

## Resolution

**Yes. The burn-in can restart on a config-only guard, and the Reader re-enables it when they choose.**

1. **The guard** (applied to `$PHY_HOME/config.toml` on 2026-10-26; `phy status` confirmed it loads): `read.always_threshold = 0.95`, `budget.weekly_usd = 5`, `read.daily_quota = 3`, `read.weekly_ceiling = 20`. No new Release is needed, because `config.toml` isn't part of a Release. The Reader lowered the budget from $20 to **$5 a week**. That's about 20 Reads at about $0.21, plus about $0.35 of Filter. Quota 3 × 7 days matches the ceiling of 20, and the review queue grows by about 20 Cards a week. Until the predictive guardrail lands, one run can overshoot by up to 3 Reads (about $0.60, or about $1.90 if all three are long).
2. **No deadline.** The guard holds indefinitely. Post-mortem fixes 1, 2 and 4–6 ride the amended cut and don't have to ship before 2026-11-02. Downtime is still bounded by the 20-Read ceiling and the $5.
3. **Account** (Reader, before re-enabling): top up **$20**, and set an org **monthly** Console spend limit of **$25**. The research found Console limits are monthly only; at zero balance Filter and `count_tokens` fail too.
4. **Shipped defaults** change to the same values in a fix slice: `src/phy/defaults/config.toml`, the QUICK_START table, and SPEC §11's Read row and guardrail.
5. **Golden eval spend** counts against `budget.weekly_usd`, but eval Reads don't count against `read.weekly_ceiling`. Build slice 14 records this. An eval is about $0.60.
6. **The clock:** a day counts when the scheduled `phy daily` runs with Watch `ok` and the mark advancing. Filter, Read or Verify failures don't reset it but must be fixed. Manual runs don't count, and neither does a `RunAtLoad` run that doesn't advance the mark. A fix shipped with `phy schedule update` doesn't reset it. A Watch failure or a missed day restarts it at 0.
7. **When:** the Reader runs `uv run phy schedule install` when they choose, possibly once more slices are built. Day 1 is the first scheduled run after that which advances the mark. The date is recorded in build ticket 17.

Seen while applying the guard (left for [Sign off the calls](19-sign-off-slice-calls.md)): `$PHY_HOME/config.toml` has `read.prompt_version = "v1"`, while the default is `v2`, and `phy status` says `release: none installed`.
