# Read selection and the guardrail: bounding spend per run

Type: grilling
Status: resolved
Blocked by: 13
Assignee: Saul

## Question

How should Read selection and the budget guardrail bound what one run, and one week, can spend? The first scheduled run read 50 Papers for $9.83 in one go, and $19.50 went in about 14 hours across the ISO-week reset. Decide:

1. **The per-run cap.** Should `daily_quota` (with unused quota carried within the week) apply to `always` picks too, or should there be a separate `read.daily_max`? What does a backlog drain look like: a first run after a 14-day backfill, or a week with the schedule off?
2. **A predictive guardrail.** Before each pick, estimate its cost from the flattened token count and the price table, and stop selecting when spend plus the estimate would pass the limit. Should the estimate use `count_tokens` or chars/4? How should output tokens be estimated?
3. **The window.** ISO week, a rolling 7 days, or an added `budget.daily_usd`? The Monitoring page's spend tile uses the ISO week ([Monitoring page](11-monitoring-page.md)), so a change must keep the tile and the guardrail agreeing.
4. **`always_threshold`.** 85 of 102 screened-in Papers at ≥ 0.9 scored exactly 0.90, because the Filter scale is anchored at 0.9/0.7/0.5. Is "always" still a useful idea on an anchored scale? If not, how are ties within quota ordered?
5. **The review backlog.** 97 Cards are unreviewed, which is several weeks at the 4.5 h attention budget. Should the per-run cap be sized to review attention as well as money? What happens to the existing backlog?

## Context

- Settled by [Restart the burn-in](14-restart-burn-in.md), not to be reopened here: the budget is $5 a week (one budget, Golden eval included), with `daily_quota` 3, `weekly_ceiling` 20 and `always_threshold` 0.95. This ticket decides the code behaviour behind them: whether to cap `always` per run, the predictive estimate, the window, and the backlog.

- [First scheduled run post-mortem](../../m0-build/postmortems/2026-10-26-first-scheduled-run.md), causes 1–5 and changes 1–3.
- [Anthropic API facts for Read spend control](13-read-spend-api-facts.md) (token counting, billing errors).
- From the API facts: chars/4 underestimates LaTeX by about 2x, so an estimate needs chars/2 or `count_tokens`. Console caps are monthly only, and no API reads the balance.
- Built in [Read selection, phy daily and phy status](../../m0-build/issues/10-selection-daily-status.md); SPEC §7.3 and §11.

## Resolution

**`always` becomes a priority within the quota. A per-Paper cost check stops Read before the budget is passed. The ISO week stays the window everywhere. Ties are broken toward Papers that matter to several questions, and toward new Papers.** The config values ($5, quota 3, ceiling 20, threshold 0.95) were settled in [Restart the burn-in](14-restart-burn-in.md).

Facts it rests on (2026-10-26, from `phy.db`): about 45 Papers are screened in a day against 3 Reads a day, and 579 screened-in Papers have no Card, so selection is really "today's best 3". Successful Reads cost a mean of $0.198 (p90 $0.33, max $0.62). Output tokens: median 3,353, max 5,039 for a good Card.

1. **`always` inside the quota.** Papers at or over `read.always_threshold` go first, ahead of Stale re-cards, but never past the day's quota. A must-read past the quota waits a day. There's no `read.daily_max`. In `plan()`, `room` stops subtracting `always`, and `always` is cut to the quota like the rest.
2. **Carried quota stays.** Unused quota carries within the ISO week, as built. After downtime it's bounded by `weekly_ceiling` and the budget.
3. **The predictive check.** Just before each Paper's call, after flattening, Read compares spend so far this ISO week plus that Paper's estimate with `budget.weekly_usd`. If it would pass, Read makes no call, logs one WARNING `read.budget_reached`, and stops for the run. The Paper stays unCarded and is first in line next week. The existing check before selection stays as the early exit.
4. **The estimate.** One shared `estimate_cost()`: input tokens ≈ flattened characters / 2 (measured about 1.98 characters per token on LaTeX), priced at the rate Read will actually pay for input (the cache-write rate while paper-text caching is on), plus a fixed 5,000 output tokens at the output rate. No `count_tokens` call. [Per-Card cost](17-per-card-cost.md) decides whether the input cap reuses this count.
5. **The window stays the ISO week** (Monday 00:00 UTC) for the budget, the quota carry and the ceiling. There's no rolling window and no `budget.daily_usd`. The double spend across a Sunday and Monday is at most about $4.60, only after an idle week, and the $25 Console limit backstops it.
6. **Order within a tier:** `best_score` descending, then the sum of all question scores descending, then newest first (`arxiv_id` descending). This replaces `arxiv_id` ascending. Old ties fade out without an expiry knob.
7. **The review backlog stays.** The 95 unreviewed Cards remain in the queue, ordered by score, with no bulk action and no new Review state.

**Docs to update in the fix slice:** SPEC §7.3 (the `always` wording, the per-Paper check, the order), §11 Guardrails (predictive), and QUICK_START's `read.always_threshold` row ("first in line, within the quota").
