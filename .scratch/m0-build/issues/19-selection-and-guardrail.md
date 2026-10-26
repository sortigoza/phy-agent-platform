# Read selection and the predictive guardrail

Type: AFK
Status: open
Blocked by: 11

## Goal

One run can no longer spend a week's budget. `always` is a priority within the quota, ties go to the right Papers, and Read stops before a call that would pass the budget.

## Sources

Map tickets [Read selection and the guardrail](../../m0/issues/16-read-selection-and-guardrail.md) and [Restart the burn-in](../../m0/issues/14-restart-burn-in.md); the [post-mortem](../postmortems/2026-10-26-first-scheduled-run.md); SPEC §7.3, §12; QUICK_START §6.

## Acceptance criteria

- `plan()`: `always` picks come first, then Stale re-cards, then the others. All of them, `always` included, are cut to the day's quota (with the carry). No `read.daily_max`.
- Order within each tier: `best_score` descending, then the sum of all question scores descending (from `screenings.scores_json`), then newest first (`arxiv_id` descending).
- `estimate_cost(chars, price)`: input tokens are `chars / 2` at the `input` rate, plus 5,000 output tokens at the `output` rate.
- Just before each Paper's call, after flattening, Read compares the ISO week's spend plus `estimate_cost()` with `budget.weekly_usd`. If it would pass, Read makes no call, logs one WARNING `read.budget_reached` and stops the Stage for the run. The Paper stays unCarded. The check before selection stays.
- Shipped defaults: `budget.weekly_usd = 5`, `read.daily_quota = 3`, `read.weekly_ceiling = 20`, `read.always_threshold = 0.95`, Sonnet `cache_read = 0.10`.
- SPEC §7.3 and §12 (the Read row, Guardrails) and the QUICK_START rows match.

## Tests first

- Selection table tests:
  - 50 Papers at ≥ 0.95 with quota 3 → 3 picks;
  - `always` ahead of re-cards;
  - three Papers tied at 0.90 ordered by score sum, then newest;
  - the carry still works.
- `estimate_cost` against a hand calculation.
- Replayed Read: spend $4.90 plus a $0.20 estimate → no HTTP call to the API, one WARNING, the remaining picks untouched.

## Lift from

Nothing.

## Not in this slice

The input cap and caching (20); billing errors (21).
