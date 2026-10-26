# phy eval scores

Type: AFK
Status: open
Blocked by: 05, 09, 13, 22

## Goal

`phy eval` runs Read, Verify and Filter on the frozen Golden sources with the active (or overridden) prompts and stores the M0 Scores in `eval_runs`.

## Sources

SPEC §6 `eval_runs`, §10 Scores / When it runs; QUICK_START §8.

## Acceptance criteria

- `phy eval [--prompt read=v2] [--prompt filter=v1] [--split dev]` fails before any model call if `golden check` finds a sha256 mismatch or the manifest has no Papers.
- For each Dev Paper: Read and Verify on `golden_sources`, Filter on its metadata; eval Cards stored whole in `per_paper_json`, never in `cards`.
- Scores in `metrics_json`: grounding rate (share of quotes found), invented numbers (count; any is a hard fail), Filter decision (screened-in matches `expect_in_scope`).
- Row records `golden_version`, `split`, `prompt_versions_json`, model; every model call traced as usual.
- Migration `NNN_eval_runs` (the next free number when built, `007` as of 2026-10-26; `006` is `reviews_flags`) creates `eval_runs` with every SPEC §6 column (diff columns stay null until 15).
- Eval spend goes in `runs` like any call, so it counts against `budget.weekly_usd`. Eval Reads write no `cards` rows, so they never count against `read.weekly_ceiling` (from [Amend the M0 cut](../../m0/issues/20-amend-m0-cut.md)). Eval Reads aren't cached (slice 20).
- CLI prints the Scores per Paper and overall, and the run id.

## Tests first

- With replayed responses on 2 synthetic Golden entries: Scores match hand-computed values; an invented number marks a hard fail; a wrong Filter decision is reported.
- `--prompt` override changes `prompt_versions_json` and the loaded prompt.
- sha256 mismatch aborts with no HTTP calls made.

## Lift from

Nothing.

## Not in this slice

The diff, `/eval/<id>` and `eval accept` (15); field accuracy (M1).
