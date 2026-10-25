# Filter

Type: AFK
Status: done
Blocked by: 03, 08

## Goal

`phy filter` screens every unscreened Paper version: the code pre-filter, then one Haiku call per Candidate, stored as a screening.

## Sources

SPEC §4 (pre-filter per set, `questions.yaml`, scope notes), §6 `screenings`, §7.2; [Filter prompt v1 and its output schema](../../m0/issues/09-filter-prompt-prototype.md). Load the `claude-api` skill.

## Acceptance criteria

- Pre-filter mode per Paper is the most permissive of its sets (`none` > `keywords` > `keywords+physics`). `keywords`: any question's keyword in title or abstract and no negative keyword; `keywords+physics` also needs a physics term. Results `pass`, `fail`, `skipped` (mode `none`).
- `prompts/filter/v1.md` (`system: self`, the float-score prototype prompt) with `{{questions}}` and `{{scope_notes}}`; cache breakpoint on the system prompt; user turn is title, categories, abstract.
- Output model built from the `questions.yaml` ids (`{Qn: {reason, score}}`, reason first); scores clamped to [0, 1] with a warning.
- `screenings` row per Paper version (also for pre-filter fails, with no scores): `scores_json`, `best_score`, `screened_in` (`best_score ≥ filter.threshold`), model, prompt version, `run_id`. Catch-up: only versions with no screening; `--paper`/`--force` redo one.
- Every call traced through `llm.py`; one `runs` row per call; takes `phy.lock`.
- Migration `005_screenings` creates `screenings`.

## Tests first

- Pre-filter table test across modes, including a cross-listed Paper taking the most permissive mode.
- Output model from a 2-question and a 5-question `questions.yaml`.
- respx replay of a recorded Haiku response (record one from the prototype's `out/` data); clamp of 1.2 → 1.0 with a warning.
- Catch-up: second run screens nothing new.

## Lift from

`origin/prototype/filter-prompt:.scratch/m0/prototypes/filter/` — `score.py`, `questions.py`, `questions.yaml`, the float-score prompt (`prompts/filter/v1b.md`, shipped as `v1`; check its front matter against the ticket's resolution before shipping).

## Not in this slice

Read selection (10); the Filter decision score in eval (14).
