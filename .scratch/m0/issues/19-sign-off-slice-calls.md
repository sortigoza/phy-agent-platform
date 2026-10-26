# Sign off the calls the slice PRs left for the Reader

Type: grilling
Status: resolved
Blocked by: —
Assignee: Saul

## Question

Several build PRs made a call and asked for sign-off. Each is in code and in SPEC now, but none has been confirmed. Confirm or reverse each one. A reversal becomes part of a fix slice.

1. **Negative keywords** (Filter): a question's own `negative_keywords` veto only that question, and the top-level list vetoes the whole Paper. SPEC's "no negative keyword matches" could also mean any negative keyword fails the Paper.
2. **Filter logging** (Filter): per-Paper outcomes are logged at DEBUG, because SPEC §5's "one INFO line per paper outcome" and "under about 30 INFO lines a day" can't both hold at about 250 Candidates a day. Which SPEC rule gives way?
3. **The Stale review queue** (`/review` render): an unreviewed Stale Card is queued when its Paper has no newer Card.
4. **Reviewed Stale Cards** (`/review` writes): a Stale Card stays Stale when reviewed, so Read's yes-or-partly re-card still fires.
5. **One Review per Card in M0** (`/review` writes): a second save returns 409.
6. **`rendered_at` in a hidden form field** (`/review` writes): it's used for `seconds_spent`, and the browser can see it.
7. **`launchd.err`** (Schedule and Releases): it captures every run's console log (about 30 lines a day, never rotated), not just crashes. Should the console handler be skipped under launchd, or should the file be rotated?
8. **The job `Label`** (post-mortem observation 1): switch to a reverse-DNS label such as `io.github.sortigoza.phy.daily` now. (The signed app bundle is out of scope for M0.)
9. **The QUICK_START §3 smoke test** on a real `$PHY_HOME` (`/review` writes left it to the Reader): has it been run? Was the first Card for 1904.12072 reviewed in the UI? That is exit criterion 1.
10. **Read prompt version in `$PHY_HOME`:** the instance config has `read.prompt_version = "v1"`, but the shipped default is `v2` (acronyms expanded, "X et al."). So every scheduled Card so far used v1. Switch to v2, and should `phy` warn when the instance pins an older prompt than the default?
11. **`phy status` shows `release: none installed`,** though `v0.1.0` was installed for the first run. Did `phy schedule uninstall` remove `$PHY_HOME/app`? Check before re-enabling.

## Context

PRs "Build slice 09: Filter", "Build slice 06: /review renders a Card", "Build slice 07: /review writes Reviews and Flags" and "Build slice 11: Schedule and Releases"; [First scheduled run post-mortem](../../m0-build/postmortems/2026-10-26-first-scheduled-run.md).

## Resolution

**Eight calls are confirmed as built. Two need fix-slice changes (logging, the job Label), and two are actions for the Reader (the smoke test, the prompt version).** Item 11 was settled by the code.

1. **Negative keywords: confirmed.** A question's own list vetoes only that question, and the top-level list vetoes the whole Paper. Every per-question list is empty today.
2. **Logging: the SPEC rule changes.** Drop SPEC §5's "one INFO line per paper outcome", and keep "under about 30 INFO lines". Per-Paper successes go to DEBUG, per-Paper failures stay at WARNING or ERROR, and each Stage logs one INFO summary with counts. SQLite already holds every per-Paper outcome. *Fix slice:* apply this to Read and Verify too. The first scheduled run logged 112 lines, mostly `verify.card_verified`.
3. **The Stale review queue: confirmed.**
4. **Reviewed Stale Cards stay Stale: confirmed.**
5. **One Review per Card in M0: confirmed.**
6. **`rendered_at` in a hidden field: confirmed.**
7. **`launchd.err`: change.** *Fix slice:* when stderr isn't a terminal, the console handler logs WARNING and above only. JSONL keeps everything.
8. **Job Label: change.** *Fix slice:* use `io.github.sortigoza.phy.daily`. `phy schedule install` boots out and removes the old label's plist once.
9. **Smoke test: not yet done.** No Card for 1904.12072 exists in `$PHY_HOME`, and the 2 Reviews are on other Papers. *Reader:* right after the credit top-up, and before re-enabling the schedule, run `phy read --paper 1904.12072`, then `phy verify`, then review the Card in `/review`. That meets exit criterion 1. Build ticket 17's checklist now includes it.
10. **Prompt version: switched, with a warning to add.** `$PHY_HOME/config.toml` now has `read.prompt_version = "v2"` (2026-10-26). `phy init` had seeded `v1` before slice 03 changed the default, so all 97 earlier Cards used v1. *Fix slice:* `phy status` warns when the instance runs an older prompt version than the shipped default. The instance never follows the default silently.
11. **`release: none installed`: expected.** `phy schedule uninstall` removes the `$PHY_HOME/app` worktree (`src/phy/schedule.py`), and `install` recreates it.
