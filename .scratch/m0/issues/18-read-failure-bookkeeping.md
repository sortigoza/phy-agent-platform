# Read failure bookkeeping, and what --force does to a reviewed Card

Type: grilling
Status: resolved
Blocked by: 13
Assignee: Saul

## Question

Slice 03 left four Read behaviours "worth deciding later". The first real runs add a fifth. Now that Reviews, Flags and the `/runs` viewer are real or next, decide each:

1. **`--force` keeps the Card's id.** A re-Read replaces the content in place, so an existing Review and its Flags end up attached to content they never judged. Should `--force` on a reviewed Card make a new Card and leave the old one (and its Review) alone? Refuse? Clear the Review? How does this interact with Stale re-cards and Golden?
2. **The run is marked `ok` before the `cards` insert.** If the insert fails, the result is an `ok` run with no Card. Should both happen in one transaction, or should the order be swapped?
3. **No `runs` row when Read fails before the model call** (arXiv errors, a bad prompt, and now a Paper too long to Read). `/runs` and the failure tiles can't see those failures. Should every attempt write a row?
4. **`questions[].id` isn't checked against `questions.yaml`.** Should Verify warn, drop the entry, or mark it unsupported?
5. **Billing errors are fatal for the run.** Once the API says the credit is gone, every later call fails too. How is that detected (from [Anthropic API facts](13-read-spend-api-facts.md)), and what happens: stop Read, skip Verify, one ERROR, and does `phy status` say so?

## Context

- From [Per-Card cost](17-per-card-cost.md): a too-long Paper writes a `runs` row with `status = 'skipped'`, and selection excludes it by `arxiv_id`. Keep item 3 consistent with that. Also decide here: should a failed Read (a `max_tokens` loop, or an over-context 400 under `--force`) be selected again every day, as SPEC §7.3 says today, or should it be retried only N times?

- From the API facts: credit-balance and Console spend-limit errors are both 400 `invalid_request_error`, distinguishable only by message text. The tier's monthly cap is a 429 with `enforced_spend_limit_reached`, which the SDK retries twice first.

- PR "Build slice 03: the Read call", under "Not handled here, and worth deciding later".
- [First scheduled run post-mortem](../../m0-build/postmortems/2026-10-26-first-scheduled-run.md), change 6.
- The skipped outcome itself is decided in [Per-Card cost](17-per-card-cost.md); this ticket only decides whether it gets a `runs` row.

## Resolution

**Every Read attempt is accounted for. A reviewed Card can't be overwritten. Errors that mean the account can't pay stop the Stage. A Paper that keeps failing is given up after 3 tries.**

1. **`--force` refuses when the Card has a Review or any Flag,** with a message saying why. A new row next to the old one is impossible (one Card per Paper version), and clearing the Review would delete the Reader's judgement. Stale re-cards (a new version, a new row) and Golden (never writes `cards`) aren't affected.
2. **An insert failure after a successful call** updates that Read's `runs` row to `failed` with the insert error, and keeps the cost (the tokens were spent). The Tracer still commits its row first; no shared transaction.
3. **A `runs` row when Read fails before the model call:** already done. Slice 03's review fixes made `run()` write a failed row (`src/phy/read/stage.py`). The `skipped` row from [Per-Card cost](17-per-card-cost.md) sits alongside it.
4. **Unknown question ids:** Verify drops a `questions[]` entry whose id isn't in `questions.yaml` and adds a warning. It has never happened (154 matches across 97 Cards). The static Read schema rules out an `enum`.
5. **Errors that stop the run,** in Read and Filter alike: the 400s whose message starts with "Your credit balance is too low" or "You have reached your specified" (API or workspace usage limits), a 429 with `error.details.error_code == "enforced_spend_limit_reached"`, a 402 `billing_error`, a 401 and a 403. These are recognised in one function, with a test per case, from [Anthropic API facts](13-read-spend-api-facts.md). On one:
   - that Paper's run is marked **`aborted`**, not `failed`;
   - one ERROR is logged (`read.account_blocked` / `filter.account_blocked`);
   - the Stage makes no further calls;
   - Verify still runs;
   - `phy status` shows "Read stopped: <reason>" (or Filter) from the latest run.
6. **Retry limit:** after **3 `failed`** Read runs for an `arxiv_id`, selection excludes the Paper, as it excludes a skip. `aborted` runs don't count; transient failures do. `phy status` changes "failures not retried" to "gave up after 3 failures (N)", with each id and the last error. `phy read --paper <id> --force` always tries again.

The new `runs.status` values are `skipped` (Per-Card cost) and `aborted`. `runs.status` has no CHECK, so no migration is needed.

**Docs to update in the fix slice:** SPEC §7.3 (retry limit, `--force` refusal, run-fatal errors), §7.2 (Filter stops on run-fatal errors), §7.4 (the unknown question id warning), §9 (`phy status` lines).
