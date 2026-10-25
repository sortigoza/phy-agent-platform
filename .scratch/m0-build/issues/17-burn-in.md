# M0 burn-in

Type: HITL
Status: open
Blocked by: 11, 16

## Goal

Confirm the M0 exit criteria on the Reader's Mac. The 7-day clock starts as soon as slice 11 is done; this ticket closes when slice 16 is in too.

## Sources

SPEC §3 M0 exit criteria; QUICK_START §2–5.

## Checklist

1. After slice 11: tag a Release (`git tag -a v0.1.0 -m "…" && git push --tags`), run `uv run phy schedule install`, then `phy schedule status`. Note the start date.
2. Daily: nothing, unless `phy status` shows a failure. If a fix is needed, tag a new Release and `phy schedule update`; a missed day restarts the 7-day count only if the mark failed to advance.
3. Add the remaining seed Papers with `phy golden add` (2003.06413, 1606.02318, 1605.01735) and run `phy eval` then `phy eval accept <id>`.
4. Review Cards in `/review` on weekdays, so the Review tiles fill.
5. After slice 16 is released and installed: open `/monitor`.

## Done when

- The first Card for 1904.12072 has been reviewed in the UI (slice 07).
- `runs` shows Watch `ok` with `watch.hwm` advancing on 7 consecutive days, all unattended.
- Every M0 tile on `/monitor` has left grey.

Record the dates, the Release tags used and any fixes in this ticket when closing it.
