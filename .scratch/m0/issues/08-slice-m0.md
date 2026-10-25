# Slice M0 into implementation tickets

Type: grilling
Status: resolved
Blocked by: 02, 03, 05, 06, 07, 09, 10, 11
Assignee: Saul

## Question

How should M0 be cut into ordered, vertical-slice implementation tickets, each buildable test-first in one agent session? Each ticket needs acceptance criteria and dependencies. Start from the smoke test on 1904.12072 (`phy read --paper`, then the UI) and end at the M0 exit criteria in SPEC §3. Any fog left in the map must be resolved or explicitly assigned to a slice.

## Resolution

**M0 is cut into 17 ordered tickets in [`.scratch/m0-build/`](../../m0-build/README.md)**: local markdown, the same `Type`/`Status`/`Blocked by` convention, `Type: AFK|HITL`. Each has Goal, Sources, Acceptance criteria, Tests first, Lift from, and Not in this slice.

**Order: the smoke path first, then the pipeline, then the instruments.**
1. Skeleton and `phy init`
2. Source to flattened text
3. The Read call
4. Verify: quotes and locations
5. Verify: numbers, labels and caps
6. `/review` render
7. `/review` writes, which meets **exit criterion 1**
8. Watch
9. Filter
10. Read selection, `phy daily` and `phy status`
11. Schedule and Releases
12. `/runs`
13. Golden set
14. `phy eval` Scores
15. Run-to-run diff and `eval accept`
16. `/monitor`
17. M0 burn-in (HITL), which meets **exit criteria 2 and 3**

Verify and `/review` are each split in two to fit one session.

**Decisions:**
- **`read --paper` metadata.** `read --paper` calls OAI-PMH `GetRecord` (`arXivRaw`) and upserts with the parser Watch reuses, so the parser and rate limiter land in slice 2. It takes the latest version, bypasses Filter, and writes no screening.
- **Prototype code.** Prototype code is a reference implementation, lifted under tests written first from the SPEC. The OAI fixtures move to `tests/fixtures/`. The repo is public, so no arXiv source goes in git and LaTeX tests use synthetic `.tex`.
- **Migrations.** Each slice adds a migration for its own tables, and a merged migration is never edited.
- **Unattended runs execute a Release, never the dev clone.** A Release is an annotated semver tag `vX.Y.Z` on `main`, cut by the Reader (phy never tags), with pre-release tags ignored. `phy schedule install` checks out the newest one as a detached `git worktree` at `$PHY_HOME/app` and runs `uv sync`. A newer Release shows as an amber "update available" top-bar badge (via `release_status()`, stubbed in slice 6 and implemented in slice 11), as a `phy status` line and as an INFO log event, never as a red tile. `phy schedule update` takes `phy.lock`, refuses downgrades, moves the worktree to the newest Release and runs `uv sync`. The check is local because the worktree shares the dev repo's tags.
- **Burn-in starts early.** The 7-day burn-in clock starts as soon as slice 11 ships, while slices 12–16 are built. Burn-in closes once there have been 7 consecutive days with Watch `ok` and the high-water mark advancing, and every tile has left grey.

**Fog assignment:** none was left. The CLI extras in QUICK_START are assigned: `phy flags` to slice 7, `watch --since`/`--reset` to slice 8, `--force` to each Stage slice, and `phy schema export` to slice 3.

**Spec changes made:**
- SPEC §5 Scheduling (Releases, the run worktree, the update badge) and the §6 tree (`app/`).
- QUICK_START §5 (cutting a Release, `phy schedule update`).
- GLOSSARY: **Release**.
