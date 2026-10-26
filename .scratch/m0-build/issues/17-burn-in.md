# M0 burn-in

Type: HITL
Status: open
Blocked by: 11, 16

## Goal

Confirm the M0 exit criteria on the Reader's Mac. The 7-day clock starts as soon as slice 11 is done; this ticket closes when slice 16 is in too.

## Sources

SPEC §3 M0 exit criteria; QUICK_START §2–5.

## Checklist

1. After slice 11: tag a Release (`git tag -a v0.1.0 -m "…" && git push --tags`). *(Done: `v0.1.0`. The first scheduled run on 2026-10-26 overspent and the schedule was uninstalled; see the [post-mortem](../postmortems/2026-10-26-first-scheduled-run.md).)*
2. Before re-enabling (from the map ticket [Restart the burn-in](../../m0/issues/14-restart-burn-in.md)):
   - Top up the Anthropic credit by $20, and set an org monthly Console spend limit of $25.
   - Check that `$PHY_HOME/config.toml` has `budget.weekly_usd = 5`, `read.daily_quota = 3`, `read.weekly_ceiling = 20` and `read.always_threshold = 0.95` (applied 2026-10-26).
   - Smoke test (exit criterion 1; see the map ticket [Sign off the calls](../../m0/issues/19-sign-off-slice-calls.md)): `phy read --paper 1904.12072`, then `phy verify`, then review the Card in `/review`. `read.prompt_version` is `v2` (switched 2026-10-26).
   - When you choose, run `uv run phy schedule install`, then `phy schedule status`.
3. **The clock.** Day 1 is the first *scheduled* run after the install that advances the mark. The `RunAtLoad` run counts only if it advances the mark. A day counts when Watch is `ok` and the mark advances. Filter, Read or Verify failures don't reset the count, but fix them: tag a new Release and run `phy schedule update`, which doesn't reset it either. A Watch failure or a missed day restarts the count at 0. Manual runs never count.
   - When `phy schedule update` installs the fix Release that drops `verify.normalize` (map ticket [Keep, wire up or drop the verify.normalize knob](../../m0/issues/12-verify-normalize-knob.md)), delete that line from `$PHY_HOME/config.toml` at the same time, then run `phy verify --force` once.
4. Add the remaining seed Papers with `phy golden add` (2003.06413, 1606.02318, 1605.01735) and run `phy eval` then `phy eval accept <id>`.
5. Review Cards in `/review` on weekdays, so the Review tiles fill.
6. After slice 16 is released and installed: open `/monitor`.

## Done when

- The first Card for 1904.12072 has been reviewed in the UI (slice 07).
- `runs` shows Watch `ok` with `watch.hwm` advancing on 7 consecutive days, all unattended.
- Every M0 tile on `/monitor` has left grey.

Record the dates, the Release tags used and any fixes in this ticket when closing it.
