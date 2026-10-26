# Amend the M0 cut with the fix slices

Type: grilling
Status: open
Blocked by: 12, 14, 16, 17, 18, 19

## Question

Given the answers to the tickets above, which build tickets have to be added to or changed in `.scratch/m0-build/`, and where do they go in the order? Write them in the same format, test-first and one session each. Settle:

- Which fixes must ship in a Release before Read resumes (see [Restart the burn-in](14-restart-burn-in.md) for the deadline), and which can ride with slices 12–16.
- Changes to the open slices: `/runs` (pre-call failure rows, the skipped outcome), Golden set and eval (paper-text caching on re-Reads), `/monitor` (a "too long" or skipped tile? spend tile window), and burn-in (clock restart, account checklist).
- Whether every M0 tile can still leave grey under the new caps.
- Update the build README table, the milestones line, SPEC §7.3, §11, QUICK_START and the config defaults wherever the answers changed them.

## Context

- From [Keep, wire up or drop the verify.normalize knob](12-verify-normalize-knob.md), fix-slice items: drop `verify.normalize` with a load error naming the line; six `canonicalise` rules, each with a test; a length rule of 5 words or 30 characters (SPEC §7.4); `phy verify --force` over every Card in the rollout.

- From [Read failure bookkeeping](18-read-failure-bookkeeping.md), fix-slice items: `--force` refuses a Card with a Review or Flags; an insert failure marks the run `failed`; Verify drops unknown question ids with a warning; account-blocked errors abort Read and Filter (`aborted` runs, one ERROR, a `phy status` line); selection excludes a Paper after 3 `failed` Read runs. `/runs` and `/monitor` must know the `skipped` and `aborted` statuses.

- From [Per-Card cost](17-per-card-cost.md), fix-slice items: drop Read `cache_control` (Golden included); `READ_MAX_TOKENS` 8,000; `read.max_input_tokens` 150k with a `skipped` runs row and the selection exclusion; "too long to Read" in `phy status`; `cache_read` 0.10 in the shipped prices. Open for this ticket: a `/monitor` tile for relevant Papers skipped as too long.

- From [Read selection and the guardrail](16-read-selection-and-guardrail.md), fix-slice items: `always` within the quota in `plan()`; `estimate_cost()` and a per-Paper budget stop before each call; tie order (score, score sum, newest); updates to SPEC §7.3, §11 and QUICK_START.

- From [Sign off the calls](19-sign-off-slice-calls.md), fix-slice items: per-Paper successes at DEBUG with one INFO summary per Stage (Filter, Read, Verify; SPEC §5 drops "one INFO line per paper outcome"); the console handler at WARNING+ when stderr isn't a terminal; Label `io.github.sortigoza.phy.daily`, with install removing the old one; a `phy status` warning when the instance prompt version is older than the shipped default.

- From [Restart the burn-in](14-restart-burn-in.md): a fix slice changes the shipped defaults, QUICK_START and SPEC §11 to $5 / 3 / 20 / 0.95. Build slice 14 counts eval spend against `budget.weekly_usd` but not eval Reads against `weekly_ceiling`. Build ticket 17's checklist is already updated. Nothing has to ship before 2026-11-02.

The original cut: [Slice M0 into implementation tickets](08-slice-m0.md).
