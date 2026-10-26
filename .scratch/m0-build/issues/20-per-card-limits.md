# Per-Card limits: no caching, output and input caps

Type: AFK
Status: open
Blocked by: 19

## Goal

No single Card can cost more than about $0.35, plus about $0.08 if the output loops. A Paper too long to Read is skipped and shown, not failed.

## Sources

Map tickets [Per-Card cost](../../m0/issues/17-per-card-cost.md) and [Diagnose the max_tokens runaway](../../m0/issues/15-max-tokens-runaway.md); SPEC §5, §7.3; QUICK_START §6.

## Acceptance criteria

- `llm.read_card` sends no `cache_control`, so neither scheduled Reads, Golden nor `--force` is cached. The docstring's claim about a reusable prefix is fixed. Filter keeps its breakpoint.
- `READ_MAX_TOKENS = 8_000`.
- New `read.max_input_tokens = 150000`, using `estimate_cost()`'s count (`chars / 2`), checked at the same point as the budget check. Over it, Read makes no call and writes a `runs` row with `status = 'skipped'` and `error = 'too_long: <n> tokens'`.
- Selection excludes any Paper (matched on `arxiv_id`) with a skipped Read run. A skip doesn't count against the quota and doesn't refill today's picks.
- `phy read --paper <id> --force` ignores the cap. An over-context 400 is recorded as a failed run, as today.
- `phy status` shows "too long to Read (N)", with each id, estimated tokens and `best_score`.
- SPEC §5 (no Read caching), §7.3 (cap and skip) and the QUICK_START row are updated.

## Tests first

- The replayed Read request has no `cache_control` and `max_tokens` 8000.
- A 400k-character `flattened.txt` → no API call, a `skipped` row, excluded from the next `plan()`; with `--force` the call is made.
- `phy status` shows the skipped Paper.

## Lift from

Nothing.

## Not in this slice

A `/monitor` count of skips (16).
