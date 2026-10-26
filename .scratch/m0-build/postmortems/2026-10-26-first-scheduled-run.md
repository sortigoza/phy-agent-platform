# Post-mortem: the first scheduled run (2026-10-26)

Status: schedule disabled (`phy schedule uninstall`) until the fixes below land. Release `v0.1.0` is tagged and pushed.

## What happened

`phy schedule install` loaded the job at 08:44 UTC, and `RunAtLoad` started `phy daily` from Release `v0.1.0` right away. The run took 28 minutes and exited 0.

| Stage | Result | Cost |
| --- | --- | --- |
| Watch | 8 sets; the mark moved to 2026-10-26 | — |
| Filter | 556 Paper versions → 135 Candidates → 45 screened in, 0 failed calls | $0.05 |
| Read | 50 selected (all `always`); 47 Cards, 3 failed | $9.83 |
| Verify | 47 verified | — |

The three Read failures:
- **2610.13589:** the output hit `max_tokens` (16,000 output tokens, no thinking). That cost $0.26 and produced no Card.
- **2610.30257:** the flattened text came to 1.7M tokens, over the 1M context. The API returned 400 and nothing was charged.
- **2610.31935:** "credit balance is too low". The Anthropic account ran dry on the run's last call.

## Why it used half the weekly budget in one run

**Per-Card cost is on plan.** The median Card cost $0.16 (range $0.07–$0.62) on a median 52k-token paper; the largest, 231k tokens, cost $0.62. SPEC §11 budgets about $8.40 a week for up to 40 Reads. This run spent the whole week's Read plan in one go.

**The volume was the problem: a 14-day backlog went through in one day.** The causes stack up:

1. **`always` is not capped per day.** `plan()` takes every Candidate at or over `read.always_threshold`. `daily_quota` (8) limits only the extra picks on top of those. The only cap on `always` is `weekly_ceiling` (50), and this run hit it exactly: `always=50 quota=0`.
2. **`always_threshold` = 0.9 sits on a cluster of Filter scores.** 85 of the 102 screened-in Papers at ≥ 0.9 scored exactly 0.90. Only 14 reach 0.95. The threshold was meant for rare must-reads, but it caught a fifth of the screened-in pool. Filter is loose as well: 677 of 1,852 Candidates (37%) are screened in at `filter.threshold` 0.5.
3. **The backlog came from the first harvest.** `watch.backfill_days` = 14 harvested 6,078 Papers. Of the 102 Papers at ≥ 0.9, 94 were screened on 2026-10-25 and only 8 today. Steady state is about 8 a day.
4. **The ISO-week window resets on Monday.** The manual runs on Sunday 2026-10-25 (19:11–19:39 UTC) read 51 Papers for $9.66, which counted against last week. Today is Monday, so the window and the 50-Read ceiling reset at 00:00 UTC. Together that's **$19.50 of Read in about 14 hours**, and the guardrail never saw more than $9.87 at once.
5. **The guardrail checks only before selection.** It stops Read once spend has *already* reached `budget.weekly_usd`. It never estimates what the day's picks will cost, so one run can overshoot by up to a whole ceiling's worth of Reads (about $10).
6. **The account balance was lower than the guardrail.** The Anthropic credit ran out at about $20 total. That's a hard external limit the pipeline doesn't know about, and it ended up acting as the real guardrail.

**Waste inside the cost: the paper cache is never read.** Every Read marks the paper text as a cache breakpoint, so 3.14M tokens were written at the cache-write price ($2.50/M instead of $2.00/M), and none were read back (`cache_read` = 0). Each paper is Read once, so that premium bought nothing. It cost **$1.57, 16% of the run.** The cache only pays off for re-Reads (Golden eval, `--force`).

## What went right

- The install and schedule path worked end to end. launchd ran `uv run --frozen phy daily` from `$PHY_HOME/app` on `v0.1.0`, auth worked with only `PHY_HOME` set, and `phy schedule status` showed the loaded job and the exit code.
- Per-Paper failures stayed per Paper: the other 47 Reads and Verify still ran.
- `weekly_ceiling` did cap the run at 50 Reads, so the worst case was bounded.

## What to change

Ordered by how much each protects the budget. The first three are needed before re-enabling.

1. **Cap Read per run** (code). Apply `daily_quota`, plus the unused quota carried within the week, to `always` picks too, or add a `read.daily_max`. A backlog then drains over several days instead of in one run.
2. **Make the guardrail predictive** (code). Before each Read, estimate its cost from the flattened token count, which the dry-run already computes, and the price table. Stop selecting when spend plus the estimate would pass the limit. Also consider a rolling 7-day window, or a `budget.daily_usd`, so a Sunday and Monday can't spend two weeks' budget between them.
3. **Raise `read.always_threshold` to 0.95** (config, today). That leaves the 14 true must-reads. All of them are already carded, so nothing is lost.
4. **Drop `cache_control` on the paper text for Read** (code). That saves about 16% per Card. Keep it for Golden eval re-Reads, or wherever a cache hit is likely.
5. **Skip Papers over an input-token cap** (code and config; see observation 2). This also covers Papers too big for the context. Investigate the `max_tokens` runaway on 2610.13589 in the run viewer: 16k output tokens against a typical 3.3k.
6. **Treat a billing error as fatal for the run** (code). Once the API says the credit is gone, every later call fails too, so stop Read and log one ERROR.
7. **Keep the account in step with the guardrail** (ops). Keep the Anthropic credit above `budget.weekly_usd`, and set a Console spend cap at or below it.
8. **Tighten Filter later** (prompt or config). Screening in 37% of Candidates is high. Recalibrate on the Golden set (tickets 13–14) rather than by hand.

## Reader observations

### 1. The job shows up as "uv, item from unidentified developer"

After install, System Settings › General › Login Items & Extensions › App Background Activity lists the job as **uv**, with a generic exec icon and "Item from unidentified developer". Nothing names phy.

Why: macOS's Background Task Management labels a launch agent by the executable it runs (`ProgramArguments[0]`), not by the plist `Label`. Ours is `/opt/homebrew/bin/uv`, which has no Developer ID signature. The same identity problem affects privacy permissions (TCC: Full Disk Access, Files and Folders, and so on). A grant is recorded against the responsible executable, so a permission given to "uv" would apply to **every** uv-run program on the Mac, not just phy. That's the opposite of scoped.

Today the job needs no TCC permission. It reads `~/.phy-agent-platform` and `~/.config/anthropic`, neither of which is protected, and outbound network needs no grant. So this is about identification now, and about scoping as soon as any permission is needed: notifications in M1, or `$PHY_HOME` moved under `~/Documents`.

Options, cheapest first:
- **a. A reverse-DNS `Label`** such as `io.github.sortigoza.phy.daily`. This makes the job unique in `launchctl` and in the plist file name. It doesn't change what the Settings pane shows.
- **b. A dedicated launcher executable**, `$PHY_HOME/bin/phy-daily` (or inside `app/`), that execs `uv run --frozen phy daily`. Settings would then show `phy-daily`, so the job is at least recognisable. If the launcher is a shell script, TCC attributes to the interpreter (`/bin/sh`), so scoping gets *worse*, not better. Only a small compiled launcher has its own code identity.
- **c. A minimal signed app bundle** (recommended once permissions matter): `Phy.app` with its own bundle identifier (e.g. `io.github.sortigoza.phy`), a tiny compiled launcher as its executable, and a signature. With a Developer ID signature, Settings shows "Phy" with its icon and developer name. An ad-hoc signature still gives a stable identity on this Mac. The plist points `Program` into the bundle and sets `AssociatedBundleIdentifiers` to the bundle id, so the login item is attributed to Phy. TCC grants then attach to Phy's code identity alone, and toggling Phy off in Settings affects only phy. On macOS 13+ the bundle can register the agent itself through `SMAppService`, which is Apple's supported route and replaces hand-written plists.

Proposal: do (a) now, since it's a one-line change in `schedule.py`. Make (c) a ticket before M1 notifications. Verify on this Mac which name and identity Settings shows for each option before committing to one: the attribution rules above are from Apple's documented behaviour and should be checked here.

### 2. Skip a Paper whose input would cost too much

A long Paper costs about $2.50 per 1M cache-write tokens of input before any output. The 1.7M-token Paper (2610.30257) couldn't be Read at all, and the 231k-token one cost $0.62, four times the median.

Proposal: a `read.max_input_tokens` knob in `config.toml`. Selection, or Read just before the call, counts the flattened text's tokens. `phy read --dry-run` already does this with the free `count_tokens` endpoint; a chars/4 estimate would avoid the extra request. A Paper over the cap gets no Read call. It's recorded as **skipped** with reason `too_long` and the token count, not as a failure. It still shows in the review queue and `phy status` with a "too long to Read" badge, so the Reader can deep-read it by hand or force it with `phy read --paper <id> --force`. Hard-fail anything over the model's context window even when forced.

What a cap would have saved across all 98 Reads so far ($19.50):

| Cap | Papers skipped | Their cost |
| --- | --- | --- |
| 100k | 16 | $6.15 |
| 150k | 5 | $2.42 |

The cost of a cap is that long Papers, often the reviews and in-depth works the questions care about most, lose their Card. Start at 150k, which catches the outliers, and watch on the Monitoring page how many relevant Papers get skipped before going lower.

## Before re-enabling the schedule

- **This week is already safe.** The 50-Read ceiling is used up, so Read selects nothing until Monday 2026-11-02, and a re-enabled schedule would spend only on Filter (about $0.05 a day). The account still needs credit, or Filter fails too.
- **Expected steady state** with changes 1–3: about 8 Reads a day until `weekly_ceiling`, so at most 50 × $0.20 ≈ **$10 a week** plus Filter, within the $20 guardrail. Change 4 lowers it to about $8.50.
- **Review load matters too.** 97 Cards are unreviewed. At the 4.5 h weekly attention budget (SPEC §11), that backlog alone is several weeks of review. A daily cap keeps the queue at a size the Reader can clear.
- **Re-enable with:** `uv run phy schedule install`. The burn-in clock (ticket 17) starts then, not on 2026-10-26.
