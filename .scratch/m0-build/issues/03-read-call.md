# The Read call

Type: AFK
Status: open
Blocked by: 02

## Goal

`phy read --paper 1904.12072` makes one Sonnet call and stores a draft Card, with the full request and response traced.

## Sources

SPEC §5 Model calls / Tracer, §6 (Card models, `cards`, `runs`, prompt files), §7.3 The call / Prompt files, §8, §12 prices; [Card schema v1 and Read prompt v1](../../m0/issues/04-card-schema-and-read-prompt-prototype.md); [Review page design](../../m0/issues/05-review-page-prototype.md) (Read prompt v2 rules); [Code conventions and runtime plumbing](../../m0/issues/07-code-conventions.md). Load the `claude-api` skill.

## Acceptance criteria

- `card.py`: `CardDraft` (model output, quotes before value, `inferred` flag, one `opinion` block, nullable `baselines`/`code_data`) and `Card` (adds Support, `loc`, `match_count`, `ungrounded_numbers`). `phy schema export` writes both JSON Schemas to `schemas/`; a test fails if the committed files are stale.
- Prompt loader: `prompts/<stage>/<version>.md` with YAML front matter (`stage`, `version`, `system`, `model`, `effort`, `schema`, `params`, `notes`); `{{name}}` placeholders, a missing or unused placeholder is an error; `$` is left alone.
- `questions.py`: `render_questions()` and `render_scope_notes()`, deterministic and never showing keywords.
- Prompts shipped: `prompts/shared/v1.md`, `prompts/read/v1.md` (the prototype) and `prompts/read/v2.md` (adds acronym expansion and "Surname et al." with `{{authors}}`); config's default Read version is v2.
- `llm.py`: builds the request (shared system prompt, paper text with a cache breakpoint, Read instructions), `output_config.format` from the schema, `effort` from config; calls `client.messages.parse()`; computes cost from `config.toml` prices including cache reads and writes; hands request, response or error to the Tracer.
- `tracer.py`: `record(run, request, response, error)` appends to `$PHY_HOME/runs/<run_id>.jsonl` and fills the `runs` row (status `ok`/`failed`, tokens, cache tokens, cost, timings, `log_path`).
- `read --paper` writes a `cards` row with status `draft`, model, prompt version, schema version and `run_id`. Re-running replaces nothing unless `--force`; a failed call leaves a `failed` run and no Card.
- Migration `003_cards` creates `cards`.
- `pytest -m live` runs the real call on 1904.12072 (≈ $0.10) and asserts a valid `CardDraft` and a cache write.

## Tests first

- Schema: a hand-written valid draft parses; quotes-before-value ordering in the exported schema; committed schemas match.
- Prompt loader: front matter parsed; missing placeholder raises; LaTeX `$` survives.
- `render_questions()` output is byte-identical across calls and omits keywords.
- `llm` with respx replaying the recorded Read response from `origin/prototype/card-schema-read-prompt:.scratch/m0/prototypes/card-read/out/response.json`: the request carries the cache breakpoint after the paper text and the schema; cost matches a hand calculation; the Tracer gets one line.
- API error (respx 500 then 529) leaves a `failed` run row with the error and no Card.

## Lift from

`origin/prototype/card-schema-read-prompt:.scratch/m0/prototypes/card-read/` — `card.py`, `read_call.py`, `prompts/shared/v1.md`, `prompts/read/v1.md`, `out/response.json`; `origin/prototype/filter-prompt:.scratch/m0/prototypes/filter/questions.py`.

## Not in this slice

Verify (04–05), Read selection and quota (10), Filter's call (09).
