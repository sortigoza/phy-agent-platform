# Anthropic API facts for Read spend control

Type: research
Status: resolved
Blocked by: —

## Question

Which Anthropic API facts do the spend-control decisions depend on? Answer each from primary sources (Anthropic docs and SDK source), and give the date checked:

1. **Billing errors.** What HTTP status, error `type` and SDK exception does "credit balance is too low" come back as? Can code tell it apart from a 400 for a bad request and from a 429 rate limit without matching the message text? Which other errors mean every later call will fail too, such as a spend limit reached or an invalid key?
2. **Console spend limits.** Can an organisation or workspace set a monthly or other spend cap? What error does a request get once it's hit? Can the API read the remaining credit or the cap?
3. **Token counting.** Is `messages.count_tokens` free? What are its rate limits? Does it count a request with `output_config.format` and `cache_control` exactly as `create` would? How far off is chars/4 for LaTeX-heavy text? Use one real `flattened.txt` from `$PHY_HOME` if it helps; don't commit it, since the repo is public.
4. **Context and output limits** for `claude-sonnet-5-5`: the input context window (1M, and is it the default or a beta?), the largest `max_tokens` allowed without streaming, and whether a request over the context limit is rejected before it is charged.
5. **Prompt-caching economics.** The 5-minute and 1-hour cache-write multipliers, the read multiplier, and the minimum cacheable prefix for Sonnet and Haiku. Does a request with no `cache_control` on the paper text still get cache reads on an earlier breakpoint (system prompt plus schema)?

## Context

- Raised by the [first scheduled run post-mortem](../../m0-build/postmortems/2026-10-26-first-scheduled-run.md): one Read hit `max_tokens`, one ran over 1M input tokens, one hit the credit limit, and paper-text cache writes cost 16% of the run.
- Blocks [Read selection and the guardrail](16-read-selection-and-guardrail.md), [Per-Card cost](17-per-card-cost.md) and [Read failure bookkeeping](18-read-failure-bookkeeping.md).
- Findings go on branch `research/read-spend-api-facts` (pushed, never merged).

## Resolution

Findings are in `research/read-spend-api-facts.md` on branch `research/read-spend-api-facts` (commit `b4ab1f3`), checked 2026-10-26.

1. **Billing errors are 400 `invalid_request_error`**, not 402, and carry no machine-readable code. The docs don't describe the error, so this comes from phy's own logs. A Console spend limit also comes back as a 400 of that type. Telling either apart from a bad request (such as over-context) means matching the message text. Only the tier's monthly cap is machine-readable: a 429 with `error.details.error_code == "enforced_spend_limit_reached"`, which the SDK retries twice.
2. **Console spend limits are monthly only**, set for the org or per workspace. No API exposes the balance or the limit for an individual account.
3. **`count_tokens` is free** (5,000 requests per minute), but it fails with the same credit-balance 400 at zero balance. Whether it counts `output_config.format` exactly as `create` bills it is unconfirmed; one call once the account has credit will settle it.
4. **chars/4 underestimates LaTeX by about 2x** (about 1.98 chars per token across 98 Reads; worst ratio 2.72). It would have let the 1.7M-token Paper through as about 705k.
5. **Sonnet 5.5:** 1M context by default, 128k max output. The SDK refuses non-streaming calls with `max_tokens` above 21,333 unless an explicit `timeout` is passed. An over-context 400 reports no usage, and phy recorded $0.
6. **Caching:** writes cost 1.25x, so the post-mortem's $1.57 stands. Reads cost 0.05x ($0.10/M), but **`config.toml` has `prices.claude-sonnet-5-5.cache_read = 0.20`, twice the list price**. The minimum cacheable prefix is 512 tokens for both models.
7. **The Read system prompt has no breakpoint.** Dropping `cache_control` from the paper text removes all Read caching. Keeping reads on the system prompt plus schema needs a breakpoint there, as Filter already has.
