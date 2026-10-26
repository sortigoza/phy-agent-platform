# Anthropic API facts for Read spend control

Ticket: `.scratch/m0/issues/13-read-spend-api-facts.md` (raised by the 2026-10-26 first-scheduled-run post-mortem).
Checked: **2026-10-26**. SDK: `anthropic` 2.3.0 (the version in `uv.lock`), read from `.venv/lib/python3.13/site-packages/anthropic/`.

Sources:
- Docs (each page fetched as Markdown on 2026-10-26): [Errors](https://platform.claude.com/docs/en/api/errors), [Rate limits](https://platform.claude.com/docs/en/api/rate-limits), [Pricing](https://platform.claude.com/docs/en/about-claude/pricing), [Token counting](https://platform.claude.com/docs/en/build-with-claude/token-counting), [count_tokens API reference](https://platform.claude.com/docs/en/api/messages/count_tokens), [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching), [Context windows](https://platform.claude.com/docs/en/build-with-claude/context-windows), [Models overview](https://platform.claude.com/docs/en/about-claude/models/overview), [Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs), [Workspaces](https://platform.claude.com/docs/en/manage-claude/workspaces), [Admin API](https://platform.claude.com/docs/en/manage-claude/admin-api), [Usage and Cost API](https://platform.claude.com/docs/en/manage-claude/usage-cost-api), [Spend Limits API](https://platform.claude.com/docs/en/manage-claude/spend-limits-api).
- Console help: [How do I pay for my Claude API usage?](https://support.claude.com/en/articles/8977456-how-do-i-pay-for-my-claude-api-usage).
- Local evidence: phy's own traces and logs in `$PHY_HOME` (`runs/*.jsonl`, `logs/phy-2026-10-2{5,6}.jsonl`), which hold the raw error bodies and `usage` of every call. No paper text is quoted here.

---

## 1. Billing errors

**Answer: "credit balance is too low" comes back as HTTP 400 `invalid_request_error`, which the SDK raises as `anthropic.BadRequestError`. Its body has no machine-readable code, so only the message text tells it apart from a malformed request. A 429 is a different class (`RateLimitError`), so it can't be confused with a rate limit.**

Evidence:

- **Observed on this account.** The Read failure on 2610.31935 (`logs/phy-2026-10-26.jsonl`, 09:12:39Z) recorded this body:
  `{'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits.'}, 'request_id': 'req_011CgQbEAhANauebrXAxgMrb'}`.
  The status is 400, and there's no `error.details` field. A `count_tokens` call made for this research on 2026-10-26 got the same 400 body (`req_011CgQqPMhabnMKGeKYuhGEi`, see §3).
- **The docs don't describe this case.** The [Errors](https://platform.claude.com/docs/en/api/errors) page lists `402 billing_error` ("an issue with your billing or payment information"), but the empty-balance error isn't a 402. Neither the Errors page nor the Console help article on paying ([8977456](https://support.claude.com/en/articles/8977456-how-do-i-pay-for-my-claude-api-usage)) names the status or message for an empty balance. The help article says only: "If you run out of credits, you can no longer call the API or use the playground until you add more."
- **SDK mapping** (`anthropic/_client.py`, `_make_status_error`): 400 → `BadRequestError`, 401 → `AuthenticationError`, 403 → `PermissionDeniedError`, 404 → `NotFoundError`, 409 → `ConflictError`, 413 → `RequestTooLargeError`, 422 → `UnprocessableEntityError`, 429 → `RateLimitError`, 529 → `OverloadedError`, other ≥500 → `InternalServerError`. Any other status, **including 402**, becomes a bare `APIStatusError`. Every `APIStatusError` carries `.status_code`, `.type` (parsed from `error.type`; `ErrorType` includes `"billing_error"`) and `.body` (the parsed JSON dict, so `e.body["error"].get("details")` is available).
- **SDK retries** (`_base_client.py`, `_should_retry`): it retries 408, 409, 429 and ≥500, unless the server sends `x-should-retry`. It doesn't retry 400, 401, 402, 403 or 404. A credit-balance 400 therefore fails at once, but a spend-cap 429 is retried twice before it surfaces. The docs don't say whether the spend-cap 429 carries `x-should-retry: false`.

Errors that mean every later call will fail too, until a human acts:

| Condition | Status / `error.type` | SDK class | Machine-readable marker | Source |
| --- | --- | --- | --- | --- |
| Prepaid credit balance empty | 400 `invalid_request_error` | `BadRequestError` | none; message starts `Your credit balance is too low` | observed (above) |
| Org or workspace spend limit **you set** | 400 `invalid_request_error` | `BadRequestError` | none; message starts `You have reached your specified API usage limits` / `...specified workspace API usage limits`, and states when access resumes | [Rate limits § Setting your own spend limit](https://platform.claude.com/docs/en/api/rate-limits#setting-your-own-spend-limit) |
| Usage tier's monthly spend cap | 429 `rate_limit_error` | `RateLimitError` | `error.details.error_code == "enforced_spend_limit_reached"`; no `retry-after` header | [Rate limits § Reaching your spend cap](https://platform.claude.com/docs/en/api/rate-limits#reaching-your-spend-cap) |
| Billing or payment problem | 402 `billing_error` | `APIStatusError` (no subclass) | `.type == "billing_error"` | [Errors](https://platform.claude.com/docs/en/api/errors) |
| Invalid, revoked or expired key or token | 401 `authentication_error` | `AuthenticationError` | status / type | [Errors](https://platform.claude.com/docs/en/api/errors) |
| Credential lacks permission | 403 `permission_error` | `PermissionDeniedError` | status / type | [Errors](https://platform.claude.com/docs/en/api/errors) |
| Model unknown or unavailable to the org | 404 `not_found_error` | `NotFoundError` | message starts `model:` | [Errors](https://platform.claude.com/docs/en/api/errors) |

A plain rate limit is also a 429 `rate_limit_error`, but it has a `retry-after` header and no `enforced_spend_limit_reached` code ([Rate limits § Response headers](https://platform.claude.com/docs/en/api/rate-limits#response-headers)).

Other 400s that are per-request, not run-fatal, come back with the same type and class: the over-context 400 (`prompt is too long: 1706026 tokens > 1000000 maximum`, observed on 2610.30257), schema errors and bad parameters. So status and type alone can't separate "this Paper's request is bad" from "the account is out of money". Only the message text can. The Errors page does note that `type` values "may expand" over time.

## 2. Console spend limits

**Answer: yes. An organisation can set a monthly spend limit below its tier's cap on the Console Billing page. A non-default workspace can have its own monthly spend limit. Hitting either returns a 400 `invalid_request_error`. The tier cap itself returns a 429 with `enforced_spend_limit_reached`. No API documented for Console (non-Enterprise) organisations returns the remaining credit balance or the spend limit.**

Evidence:

- **Tier caps** ([Rate limits § Spend limits](https://platform.claude.com/docs/en/api/rate-limits#spend-limits)): Start $500, Build $1,000, Scale $200,000 a month; Custom has none. After the cap, "API usage pauses until 00:00 UTC on the first day of the next month". The error is 429 `rate_limit_error` with `details.error_code: "enforced_spend_limit_reached"` and no `retry-after`.
- **Your own org limit**: Billing page → Spend limits → Adjust/Set limit. It can't exceed the tier cap. At the limit: "requests return HTTP 400 with error type `invalid_request_error`. The message starts with `You have reached your specified API usage limits` ... and states when access resumes." The page describes these limits as monthly. It doesn't document daily or weekly limits.
- **Workspace limits** ([Workspaces](https://platform.claude.com/docs/en/manage-claude/workspaces), [Rate limits § Setting lower limits for workspaces](https://platform.claude.com/docs/en/api/rate-limits#setting-lower-limits-for-workspaces)): set them on Console → Workspaces → select a workspace → Spend limits, to "cap monthly spending and configure alerts when spending reaches certain thresholds". "You can't set spend limits on the default Workspace." At the limit, the message says `...specified workspace API usage limits`.
- **Prepaid credit** ([help 8977456](https://support.claude.com/en/articles/8977456-how-do-i-pay-for-my-claude-api-usage)): the balance and usage show on the Billing page. Auto-reload "purchases additional credits automatically when your balance falls below a threshold you set". The article says nothing about reading the balance through an API.
- **Reading balance or cap through the API: not available for this account type.**
  - The [Admin API](https://platform.claude.com/docs/en/manage-claude/admin-api) "is unavailable for individual accounts". This account is "Saul's Individual Org" (per `ant auth status`).
  - The [Usage and Cost API](https://platform.claude.com/docs/en/manage-claude/usage-cost-api) returns historical usage and cost, not balance. It needs an Admin API credential.
  - The [Spend Limits API](https://platform.claude.com/docs/en/manage-claude/spend-limits-api) is "available to Claude Enterprise organizations only. It is not available to Claude Platform (Claude Console) organizations."
  - Messages responses carry `anthropic-ratelimit-*` headers (rate limits, not money).
  - No documented endpoint or header returns the prepaid balance. That's an absence in the docs, not an explicit statement.

## 3. Token counting

**Answer: `count_tokens` is free and has its own RPM limit (Start tier: 5,000 RPM), separate from Messages. But it is refused with the same credit-balance 400 when the balance is empty. It accepts `output_config` (format and effort) and `cache_control`. The docs call its count "an estimate" that "might differ by a small amount", and it applies no caching logic. On LaTeX, chars/4 is off by about 2x in the unsafe direction: the real count is a median of 1.99x chars/4 (range 1.50x–2.72x over 98 Reads).**

Evidence from the docs ([Token counting](https://platform.claude.com/docs/en/build-with-claude/token-counting)):

- "Token counting is **free to use** but subject to requests per minute rate limits based on your usage tier": Start 5,000, Build 10,000, Scale 20,000 RPM. "Token counting and message creation have separate and independent rate limits."
- "The token count is an **estimate**. In some cases, the actual number of input tokens used when creating a message might differ by a small amount." Also: "Token counts might include tokens added automatically by Anthropic for system optimizations. You are not billed for system-added tokens."
- On caching: "token counting provides an estimate without using caching logic. Although you may provide `cache_control` blocks in your token counting request, prompt caching only occurs during actual message creation." The count is a total. It doesn't say which tokens would be cache writes or reads.
- The [count_tokens API reference](https://platform.claude.com/docs/en/api/messages/count_tokens) lists `output_config` (with `effort` and `format`), `cache_control`, `system`, `thinking`, `tool_choice` and `tools` as parameters. The SDK 2.3.0 `messages.count_tokens` signature takes the same names.
- [Structured outputs § Prompt modification and token costs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs): with `output_config.format`, "Claude automatically receives an additional system prompt explaining the expected output format", which costs input tokens. The docs don't say explicitly whether `count_tokens` includes this injected prompt. It accepts `output_config.format`, but I couldn't confirm the effect with a live call (see below).
- Tokenizer: Claude 4.7 and later models (Sonnet 5.5 included) use a newer tokenizer that "produces approximately 30 percent more tokens than on earlier models". Counts must come from the model actually used.

Live check on 2026-10-26:

- I replayed one traced Read request (2512.14566v2: system, `cache_control`, `output_config` with effort and format, billed at 20,066 input tokens) through `client.messages.count_tokens` with the `ant auth login` OAuth profile. The call returned **HTTP 400 `invalid_request_error`, "Your credit balance is too low to access the Anthropic API..."** (`req_011CgQqPMhabnMKGeKYuhGEi`). So "free" doesn't mean "available at zero balance". Whether `count_tokens` matches `create` exactly for a request with `output_config.format` is still **unconfirmed**. One call once the account has credit would settle it: run the same replay script and compare with 20,066.

chars/4 against real tokens on LaTeX (computed offline from phy's traces, no API call):

- **Data**: every successful Read in `$PHY_HOME/runs` (n = 98, `claude-sonnet-5-5`). Billed input = `input_tokens + cache_creation_input_tokens + cache_read_input_tokens`, against the character length of the `<paper>` block. The non-paper part of the request is constant: 13,299 characters of system prompt, instructions and schema.
- **Fit**: tokens ≈ 0.505 × paper_chars + 1,733. That's **1.98 characters per token** on the flattened paper text, not 4.
- **Paper-only tokens ÷ (paper chars / 4)**: median **1.99**, p5 1.72, p95 2.40, min 1.50, max 2.72.
- **Whole request ÷ (all chars / 4)**: median 1.81, min 1.39, max 2.35.
- **Over-context paper 2610.30257**: 2,812,061 paper characters and 1,706,026 tokens (from the 400 message) give 1.65 chars/token, 2.42x chars/4. chars/4 would have estimated about 705k tokens and called it under the 1M limit.
- The Models overview's own rule of thumb, "1M tokens is roughly ... 2.5M Unicode characters" (2.5 chars/token), is for general text. LaTeX here is denser.

## 4. Context and output limits for `claude-sonnet-5-5`

**Answer: the context window is 1M tokens, the default with no beta header, at standard pricing across the whole window. Max output is 128k. The API accepts `max_tokens` up to 128k without streaming, but the Python SDK refuses a non-streaming call above 21,333 unless you pass an explicit `timeout`. An input over the window is rejected with a 400. The docs don't say whether that 400 is billed, but no usage is returned and phy recorded $0.**

Evidence:

- [Models overview](https://platform.claude.com/docs/en/about-claude/models/overview): Sonnet 5.5 context window 1M tokens, max output 128K tokens. Max output is the "Synchronous Messages API limit". Batches allow up to 300k with the `output-300k-2026-03-24` beta. Default effort for Sonnet 5.5 is `high`; phy sets `medium`.
- [Context windows](https://platform.claude.com/docs/en/build-with-claude/context-windows): "For every model with a 1M-token context window, 1M is the default: you don't need a beta header, and long-context requests are billed at standard pricing, except on Claude Haiku 5.5, where prompts over 100,000 tokens cost more."
- Over-limit input: "If the input alone already exceeds the model's context window, the API returns a 400 `invalid_request_error` ("prompt is too long") on every model." When input plus `max_tokens` exceeds the window, the request is accepted. If generation then reaches the limit, it stops with `stop_reason: "model_context_window_exceeded"`.
- Charging for the over-limit 400: **no explicit statement in the docs.** Observed: the 400 for 2610.30257 has no `usage`, and phy's trace records `cost_usd 0.0`.
- Thinking tokens are a subset of `max_tokens` and are billed as output ([Context windows](https://platform.claude.com/docs/en/build-with-claude/context-windows)). A run that stops at `max_tokens` is billed for everything it generated: the 2610.13589 Read cost $0.26 for no Card.
- **SDK non-streaming guard** (`_base_client.py`, `_calculate_nonstreaming_timeout`). It applies only when the call isn't streamed and the client timeout is the default:
  ```python
  expected_time = 60 * 60 * max_tokens / 128_000
  if expected_time > 60 * 10 or (max_nonstreaming_tokens and max_tokens > max_nonstreaming_tokens):
      raise ValueError("Streaming is required for operations that may take longer than 10 minutes. ...")
  ```
  This gives a ceiling of `max_tokens ≤ 21,333`. `MODEL_NONSTREAMING_TOKENS` lists only old Opus 4/4.1 IDs, so nothing lower applies to Sonnet 5.5. Passing an explicit `timeout` (per request or on the client) skips this guard. It's a client-side check, not an API limit.

## 5. Prompt-caching economics

**Answer: on Sonnet 5.5, a 5-minute cache write costs 1.25x base input and a 1-hour write costs 2x. Reads cost 0.05x, not the general 0.1x. The minimum cacheable prefix is 512 tokens for both Sonnet 5.5 and Haiku 5.5. A request with no breakpoint on the paper text still reads an entry written at an earlier breakpoint, such as the system prompt. But only if that earlier block itself carries `cache_control` in the requests that write it. Today's Read request has no breakpoint on the system prompt, so dropping the paper's breakpoint alone gives no caching at all.**

Evidence:

- **Multipliers** ([Prompt caching § Pricing](https://platform.claude.com/docs/en/build-with-claude/prompt-caching), [Pricing](https://platform.claude.com/docs/en/about-claude/pricing)): "5-minute cache write | 1.25x base input price"; "1-hour cache write | 2x base input price"; "Cache read (hit) | 0.1x base input price (0.025x on Claude Fable 5.1 and Claude Mythos 5.1; 0.05x on Claude Opus 5.5 and Claude Sonnet 5.5)".

  | Model | Base input | 5m write | 1h write | Cache read | Output |
  | --- | --- | --- | --- | --- | --- |
  | Sonnet 5.5 | $2.00 | $2.50 | $4.00 | **$0.10** | $10.00 |
  | Haiku 5.5 (prompt ≤ 100k) | $0.10 | $0.125 | $0.20 | $0.01 | $0.50 |
  | Haiku 5.5 (prompt > 100k) | $0.50 | $0.625 | $1.00 | $0.05 | $2.50 |
  | Opus 5.5 | $4.00 | $5.00 | $8.00 | $0.20 | $20.00 |

  Haiku 5.5's prompt length counts cache reads and writes, and a request over 100k pays the higher rate on everything ([Pricing § Long context pricing](https://platform.claude.com/docs/en/about-claude/pricing#long-context-pricing)).
- **Minimum cacheable prefix** ([Prompt caching § Cache limitations](https://platform.claude.com/docs/en/build-with-claude/prompt-caching#cache-limitations)): "512 tokens for ... Claude Sonnet 5.5 ... and Claude Haiku 5.5." A shorter prefix is processed without caching and returns no error. Both cache fields are 0.
- **How reads find earlier entries** (Prompt caching § How automatic prefix checking works):
  1. "Cache writes occur only at your breakpoint. ... The system does not write entries for any earlier position."
  2. "Cache reads look backward for entries that prior requests wrote ... walks backward one block at a time."
  3. "The lookback window is 20 blocks."
  4. "The lookback does not find stable content behind your breakpoint and cache it. It finds entries that prior requests already wrote, and writes occur only at breakpoints."

  Prefix order is `tools` → `system` → `messages`.
- The docs describe the read lookup as starting from a breakpoint in the current request. They don't explicitly say whether a request with **no** `cache_control` anywhere still reads. The multi-turn example says previously marked blocks "that ... are later not marked ... will still be considered a cache hit", but in that example the request still carries a later breakpoint. **Unconfirmed** for a request with zero breakpoints.
- **What phy's traces show**:
  - Read (98 calls): the breakpoint is on the paper block, and no request carries one on the system prompt. `cache_read_input_tokens` is 0 on all 98. 6,209,377 tokens were written, all `ephemeral_5m`, and the constant 2,648 uncached tokens per call come after the breakpoint. The system prompt was cached only inside each paper's unique prefix, so no later Read could reuse it.
  - Filter (Haiku 5.5): the breakpoint is on the system prompt, and reads work. For example, one call shows `cache_read_input_tokens: 2952`, `input_tokens: 523`. A breakpoint on a stable system prompt pays off on repeated calls.
- **Cache invalidation that matters here**:
  - "Changing the `output_config.format` parameter will invalidate any prompt cache" ([Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)).
  - Changing `output_config.effort` "always invalidates message blocks" ([Prompt caching § What invalidates the cache](https://platform.claude.com/docs/en/build-with-claude/prompt-caching#what-invalidates-the-cache)).
  - The docs don't say where the injected structured-output system prompt sits relative to a system-block breakpoint. They say only that changing the format invalidates the cache.

---

## Implications for the decisions

These are facts the blocked tickets (16 Read selection and the guardrail, 17 Per-Card cost, 18 Read failure bookkeeping) depend on. The choices are left to those tickets.

1. **Detecting an empty balance needs the message text.** An empty credit balance and a self-set spend limit are both 400 `invalid_request_error` / `BadRequestError`, the same as a per-Paper bad request (for example, an over-context paper). Neither has a structured code. The only spend condition with a structured marker is the tier cap: 429 with `error.details.error_code == "enforced_spend_limit_reached"`, which the SDK retries twice first. 401 and 403 are unambiguous by class, and 402 arrives as a bare `APIStatusError` with `.type == "billing_error"`. phy's `_translate` currently flattens all of these into `ApiError(str)` with the status in the message.
2. **No API can tell phy the balance or the Console cap** on this individual org. A Console spend limit (org-wide on the Billing page, or a non-default workspace) is monthly, and phy only finds out it was hit through the 400 above. The post-mortem's "Console spend cap at or below `budget.weekly_usd`" can only be monthly.
3. **`count_tokens` is free, but not usable at zero balance.** A guardrail or size cap that depends on it fails with the same credit 400 once the account is empty. Its count is documented as an estimate, and exact parity with `create` for `output_config.format` requests is unconfirmed.
4. **chars/4 underestimates LaTeX by about 2x** (median 1.99x, worst observed 2.72x). A chars/4 size cap or cost estimate would let Papers through at about twice the intended tokens. For the 1.7M-token paper it would have estimated about 705k tokens, under the 1M limit. A chars-based estimate would need a divisor near 2 (median) or about 1.5 (worst observed) to match these 98 Reads.
5. **Context: 1M is the default and standard-priced on Sonnet 5.5.** An over-window input fails with a 400 that returned no usage (phy recorded $0). `max_tokens` above 21,333 needs streaming, or an explicit `timeout`, in this SDK. The API itself allows 128k.
6. **Caching numbers.** The post-mortem's cache-write premium is right: $2.50 vs $2.00 is 1.25x for a 5m write on Sonnet 5.5, so its $1.57 figure stands. But `config.toml`'s Sonnet 5.5 `cache_read = 0.20` is **twice the published $0.10** (0.05x); it had no effect so far because no Read ever had a cache read. Dropping `cache_control` from the paper block alone removes all Read caching, system prompt included. Keeping system-prompt reads needs a breakpoint on the system block, whose prefix (about 1.7k tokens) is above the 512-token minimum.
