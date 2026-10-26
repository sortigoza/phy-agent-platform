# Read and Filter failure bookkeeping

Type: AFK
Status: open
Blocked by: 18

## Goal

Every Read attempt is accounted for, a reviewed Card can't be overwritten, an account that can't pay stops the Stage after one call, and a Paper that keeps failing is given up.

## Sources

Map ticket [Read failure bookkeeping](../../m0/issues/18-read-failure-bookkeeping.md); research `research/read-spend-api-facts.md` §1 on branch `research/read-spend-api-facts`; SPEC §7.2, §7.3, §9.

## Acceptance criteria

- `phy read --paper <id> --force` refuses when the Card has a Review or any Flag, saying why.
- If `write_draft_card` raises after a successful call, the Read's `runs` row becomes `failed` with the insert error, and keeps its cost.
- `llm.account_blocked(error) -> str | None` recognises:
  - a 400 whose message starts with "Your credit balance is too low" or "You have reached your specified";
  - a 429 with `error.details.error_code == "enforced_spend_limit_reached"`;
  - a 402, a 401 and a 403.
- When it fires in Read or Filter:
  - that Paper's run is `aborted`;
  - one ERROR is logged (`read.account_blocked` / `filter.account_blocked`, with the reason);
  - the Stage makes no further calls;
  - Verify still runs.
- Selection excludes a Paper (by `arxiv_id`) after 3 `failed` Read runs. `aborted` runs don't count. `--force` always tries.
- `phy status`: "Read stopped: <reason>" (or Filter) from the latest run; "failures not retried" becomes "gave up after 3 failures (N)", with each id and the last error.
- SPEC §7.2, §7.3 and §9 are updated.

## Tests first

- `account_blocked` against each recorded error body, plus an over-context 400 that must not match.
- Replayed Read with the credit-balance 400 on the first of 3 picks → one `aborted` row, no further API calls, Verify runs. The same for Filter.
- A Paper with 3 `failed` rows is not selected; with 2 failed plus 1 aborted, it is.
- `--force` on a reviewed Card is refused, and nothing changes in the db.

## Lift from

Nothing.

## Not in this slice

The `/runs` filters for the new statuses (12); the tile semantics (16).
