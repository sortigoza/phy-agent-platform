# Logging and schedule hygiene

Type: AFK
Status: open
Blocked by: 21

## Goal

A normal `phy daily` writes about a screenful of INFO, `launchd.err` holds only problems, the job has a unique label, and prompt drift is visible.

## Sources

Map ticket [Sign off the calls](../../m0/issues/19-sign-off-slice-calls.md), items 2, 7, 8 and 10; SPEC §5; the [post-mortem](../postmortems/2026-10-26-first-scheduled-run.md), observation 1.

## Acceptance criteria

- Logging:
  - per-Paper successes in Filter, Read and Verify log at DEBUG;
  - per-Paper failures stay at WARNING or ERROR;
  - each Stage logs one INFO summary with counts;
  - SPEC §5 drops "one INFO line per paper outcome".
- When stderr isn't a terminal, the console handler logs WARNING and above only. The JSONL file is unchanged.
- The launchd Label becomes `io.github.sortigoza.phy.daily`. `phy schedule install` and `update` boot out and delete the old label's plist, if present, once.
- `phy status` warns when `read.prompt_version` or `filter.prompt_version` in the instance config is older than the shipped default.

## Tests first

- A replayed `phy daily` with 3 Reads and 50 Filter calls logs under 30 INFO lines.
- Console level with a TTY and without one.
- Install with an old-label plist present → bootout called for it and the file removed (launchctl faked).
- The status warning with `v1` against a `v2` default.

## Lift from

Nothing.

## Not in this slice

The signed app bundle (out of scope for M0).
