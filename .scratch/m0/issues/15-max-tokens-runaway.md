# Diagnose the max_tokens runaway on 2610.13589

Type: task
Status: resolved
Blocked by: —
Assignee: Saul

## Question

The Read of 2610.13589 stopped at `max_tokens`: 16,000 output tokens against a typical 3.3k, $0.26, and no Card. Was that a degenerate loop (repeated quotes or items, runaway list), a legitimately huge Card, or something else? Get the facts the [Per-Card cost](17-per-card-cost.md) ticket needs.

Steps (AFK; read only, nothing committed from the trace, since the repo is public):
- Read the traces `$PHY_HOME/runs/20261026T085133Z-9a5081-2610.13589v1.jsonl` and the earlier `20261025T172410Z-e7d084-2610.13589v1.jsonl`. Did the Sunday run fail the same way?
- Describe the output's shape: which field grew, whether it repeats, and where it was cut off.
- Note the paper's input size, and whether any other Read came within 20% of `max_tokens`.
- Record the facts in the resolution. Suggest, but don't decide, what would prevent it: the soft list caps, a lower `max_tokens`, a schema `maxItems`, a prompt rule.

## Resolution

A degenerate decoding loop, not a huge Card and not a runaway list. The model wrote a normal-looking partial Card, then emitted the single character `]` over and over until it hit `max_tokens`.

1. **Only one Read of 2610.13589 ever ran.** The Sunday trace `20261025T172410Z-e7d084-2610.13589v1.jsonl` is a Filter call (Haiku, `max_tokens` 4,000, effort `low`, `end_turn`, 521 output tokens). There's no Sunday Read to compare with. `runs` agrees: one `read` row for this Paper, the Monday failure.
2. **The Monday Read request:** `claude-sonnet-5-5`, `max_tokens` 16,000, `output_config.effort` `medium`, no `thinking` block (0 thinking tokens), structured output via `json_schema`. Input was 38,466 tokens: 35,818 cache-written (the paper) + 2,648 uncached (system + instructions). `stop_reason` `max_tokens`, 16,000 output tokens, 82 s, $0.255. All 98 traced Reads used the same settings.
3. **Output shape:** 19,545 chars for 16,000 tokens (about 1.2 chars/token; good Cards run about 3). The first 5,955 chars are a valid partial Card in schema order: `tldr` (433 chars), `key_results` 5 items, `assumptions` 4, `system`, `method`, `baselines`, `claimed_advance`, and `limitations_stated` item 1. 15 quotes, all distinct, no repeated items. Every field up to there is within the typical range (see 5).
4. **The loop:** right after item 1's `value` text, still *inside the open JSON string*, the output switches to 13,590 consecutive `]` characters and nothing else until it's cut off. So about 14k of the 16k tokens (roughly one token per `]`) went to the loop. It looks like the model trying to close the nested arrays without first closing the string. `key_equations`, `key_figures`, `code_data`, `questions` and `opinion` were never reached. No good Card has a `]` run longer than 2.
5. **The typical Card (97 in `cards.card_json`):** median 10.7k chars (max 14.2k), 16 quotes (max 25). Items per list are median/max: `key_results` 5/5, `assumptions` 3/4, `limitations_stated` 3/4, `key_equations` 3/3, `key_figures` 3/3, `questions` 2/3. No good Card goes over the prompt's soft caps.
6. **Output tokens across traced Reads (98 with usage):** median 3,432, p90 3,975, max 16,000 (this one). Next highest is 5,039 (2609.39411), then 4,430. No other Read came within 20% of `max_tokens` (12,800); the largest good one used 31% of it.
7. **The paper is ordinary, if anything small.** 75k chars of flattened LaTeX (rank 28 of 100 papers; median 101k), 38k input tokens. It's a quantum-error-correction methods paper (an evolutionary search over surface-code variants) with more tables than most (10 table environments, 7 tabulars, 2 algorithms; about 77th percentile) and very few display equations (2; 6th percentile). It isn't list-heavy (2 `\item`) and has no `]` runs. Nothing in the input explains the loop.
8. **The existing caps are soft only.** The prompt (`prompts/read/v1.md`, `v2.md`) says "up to N", and `schemas/card_draft.json` says "At most N" in `description`. The schema has `minItems` but no `maxItems` or `maxLength`. That didn't matter here, because no list went over its cap.
9. **The SDK limit:** `anthropic` 2.3.0 `_calculate_nonstreaming_timeout` raises unless you stream once `3600 * max_tokens / 128_000 > 600`, so above 21,333 `max_tokens`, unless a `timeout` is passed explicitly. Read's `READ_MAX_TOKENS` = 16,000 (`src/phy/llm.py`) is under that. Raising it would also mean streaming or setting a timeout.

### Options for Per-Card cost

- **Lower `READ_MAX_TOKENS` to about 8,000.** That's 1.6x the largest good Card (5,039) and 2x p90. A repeat of this failure would then cost about $0.17 instead of $0.26 and not clip a real Card. 6,000 is tighter (about $0.15) with less headroom. This is the cheapest fix for this failure mode.
- **Treat `max_tokens` as a per-Paper failure with no automatic retry, or allow one retry.** The paper is ordinary, so a retry would probably succeed, but it doubles the worst case. Only worth it once `max_tokens` is lowered.
- **Stream Read and stop early on degeneration**, for example a run of more than 50 identical characters or output past N chars. That would have cut the loss to the first couple of thousand tokens, but it's more code.
- **Schema `maxItems` / `maxLength`** turn the soft caps into hard ones, if structured outputs honours them (check first). They guard against a runaway *list*, which isn't what happened here. They're defence in depth, not the fix.
- **A prompt rule** ("never repeat", "close every string") is unlikely to help with a decoding loop and isn't recommended on this evidence.
- **Watch for recurrence:** 1 in 98 Reads so far. Record `stop_reason` and output tokens on the Monitoring page before spending more on it.
