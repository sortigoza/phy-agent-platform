# Per-Card cost: input-token cap, the too_long outcome and paper-text caching

Type: grilling
Status: resolved
Blocked by: 13, 15
Assignee: Saul

## Question

How should Read bound the cost of a single Card? Decide:

1. **An input cap.** Add `read.max_input_tokens` (the post-mortem proposes 150k: 5 Papers and $2.42 across the 98 Reads so far)? Where is it checked: at selection, or just before the call? How is it counted?
2. **The skipped outcome.** A Paper over the cap, or over the context window, gets no Read call. How is that stored: a `cards` status, a `runs` outcome, or a new column (and does that need a migration)? How do `/review`, `phy status` and `/monitor` show it ("too long to Read")? Does `phy read --paper <id> --force` override the cap, and is anything over the context window a hard fail even when forced?
3. **Paper-text caching.** Drop `cache_control` on the paper text for Read (16% of the run's cost bought nothing)? Keep it only for Golden eval or `--force`, or nowhere? The system-prompt-plus-schema breakpoint stays either way.
4. **The output runaway.** Given what [Diagnose the max_tokens runaway](15-max-tokens-runaway.md) finds: change `max_tokens`, add schema limits, or change the prompt?

## Context

- From [Read selection and the guardrail](16-read-selection-and-guardrail.md): a shared `estimate_cost()` uses flattened characters / 2 for input tokens, plus 5k output, checked just before each call. Reuse that count for the input cap, or justify a different one. The cap check sits at the same point.

- From the API facts: the Read system prompt has no cache breakpoint, so dropping the paper-text one removes all Read caching unless the system prompt gets one. `prices.claude-sonnet-5-5.cache_read` is 0.20 in config but the list price is $0.10/M (fix the default and every `$PHY_HOME` copy). Non-streaming `max_tokens` above 21,333 needs an explicit `timeout`. Over-context requests are rejected with no usage.

- [First scheduled run post-mortem](../../m0-build/postmortems/2026-10-26-first-scheduled-run.md), changes 4–5 and observation 2.
- [Card schema v1 and Read prompt v1](04-card-schema-and-read-prompt-prototype.md) chose soft list caps.
- A skipped outcome is a new thing for the Monitoring page to count. [Amend the M0 cut](20-amend-m0-cut.md) decides whether that needs a tile.

## Resolution

**No caching in Read, an 8k output limit, and a 150k input cap that records a skip instead of a failure.** No Card can now cost more than about $0.35, plus about $0.08 if the output loops.

Facts it rests on: the only Read cache breakpoint was after the paper text, so the cached prefix was "system plus this paper", which no other call could reuse (`cache_read` = 0 across 99 Reads). Golden eval (build slice 13, now built, calls the same `llm.read_card`) re-Reads each frozen Paper once per eval, hours or days apart. The largest good Card used 5,039 output tokens, and 2610.13589 was a decoding loop ([Diagnose the max_tokens runaway](15-max-tokens-runaway.md)).

1. **No caching in Read.** Remove `cache_control` from the paper text for every Read: scheduled, Golden and `--force`. Add no system-prompt breakpoint, since about 1–2k tokens isn't worth it. Fix the `read_card` docstring's claim about a reusable prefix. Filter keeps its breakpoint. This saves about 16% a Card. `estimate_cost()` therefore prices input at `input`, not `cache_write`.
2. **`READ_MAX_TOKENS` = 8,000,** still a constant (1.6× the largest good Card). A loop then costs about $0.16 instead of $0.26. No streaming or repetition detection.
3. **Input cap:** `read.max_input_tokens = 150000` in config, counted with `estimate_cost()`'s flattened characters / 2. It's checked at the same point as the budget check: after flattening, before the call. At 150k, 5 of 99 Papers would have been skipped ($2.42).
4. **The skipped outcome:** a `runs` row with `status = 'skipped'` and `error = 'too_long: <n> tokens'`, with no migration. Selection excludes any Paper (any version, matched on `arxiv_id`) with a skipped Read run.
5. **No quota, no refill.** A skip makes no Card, so it doesn't count against the quota, and it doesn't refill today's picks.
6. **Visibility:** `phy status` shows "too long to Read (N)", with each id, estimated tokens and `best_score`. `/runs` shows the rows. `/review` doesn't change. Whether `/monitor` gets a tile is for [Amend the M0 cut](20-amend-m0-cut.md).
7. **`phy read --paper <id> --force` skips the cap.** Over-context Papers are left to the API's 400, which costs nothing, and recorded as a failed run.
8. **Price fix:** `prices.claude-sonnet-5-5.cache_read` changes from 0.20 to 0.10, the list price. Done in `$PHY_HOME/config.toml` on 2026-10-26; the shipped default changes in the fix slice.

**Docs to update in the fix slice:** SPEC §5 (Read request and caching), §7.3 (cap and skip), §11 (the Read row), QUICK_START (new `read.max_input_tokens` row), GLOSSARY if "skipped" needs a term.
