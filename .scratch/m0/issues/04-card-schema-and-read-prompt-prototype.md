# Card schema v1 and Read prompt v1

Type: prototype
Status: resolved
Blocked by: 01
Assignee: Saul

## Question

What do the Card's Pydantic schema and the Read prompt v1 look like? Prototype both and run one real Read call on arXiv:1904.12072 using `claude-sonnet-5-5` with `output_config.format`, so the Reader can react to an actual Card. Questions to settle:
- **Fields:** their order, which are required, the maximum lengths of the lists, and how "inferred" Support is defined and shown.
- **Opinion fields:** how they are labelled.
- **Key figures:** the shape and cap of `key_figures: [{label, why}]` (≤ 3 suggested), chosen from captions only.
- **Evidence:** the model writes only `quote`. Verify fills in `loc` and `match_count`, so they are not in the model's output schema.
- **Prompt layout:** how the prompt is laid out for caching (shared system prompt, then paper, then breakpoint, then instructions).
- **Prompt files:** the conventions every `prompts/<stage>/<version>.md` should follow.

Record the measured tokens and cost of the call.

## Context

The [Quote format](01-quote-format.md) answer fixes the quote rules the Read prompt must state: copy character for character from raw LaTeX, one contiguous span of 5–60 words, no ellipses. It also fixes that `key_equations` carry a `\label` key instead of an equation number.

## Answer

**The prototype held up on one real call.** A real `claude-sonnet-5-5` call on 1904.12072 at `effort: medium` produced a Card the Reader judged right in shape:
- 15 factual fields, all with a quote found verbatim: 0 unsupported, 2 inferred;
- no invented numbers, and every `\label` key exists in the source;
- one quote per field throughout.

**Measured:**

| | |
|---|---|
| Cost | $0.098 |
| Input | 27,280 tokens: 25,932 written to cache (system plus paper), 1,348 uncached (instructions); `count_tokens` without the schema gave 24,582, so the schema adds about 2.7k |
| Output | 3,074 tokens, 0 of them thinking |

The paper text is 57 KB, about 24k tokens. SPEC §12 assumed 80k in and 5k out per Read, so the real cost is about half the estimate for papers this size.

**Schema (`card/v1`).** Kept as prototyped in `card.py`.
- **Two models.** `CardDraft` is the model's output and generates `output_config.format`; it has no `loc`, `match_count` or `support`. `Card` is the stored form: `CardDraft` plus the Verify fields on each Evidence item (`found`, `loc`, `match_count`) and on each Fact (`support`).
- **Field order is generation order.** At the top level: `tldr`, `key_results` (1–5), `assumptions` (≤4), `system`, `method`, `baselines`, `claimed_advance`, `limitations_stated` (≤4), `key_equations` (≤3), `key_figures` (≤3), `code_data`, `questions` (≤4), `opinion`. Inside a Fact: `evidence` (1–2 quotes), then `value`, then `inferred`. The model writes the quote before the value.
- **Inferred.** The model sets `inferred: true` when the value follows from its quotes but isn't stated in them: it combined quotes, converted a number, or concluded something. Rewording alone is not inferred. Verify sets Support:
  - quote not found, or breaks the shape rules → `unsupported`;
  - found, and the model said inferred → `inferred`;
  - otherwise → `supported`.

  The UI shades inferred fields differently from unsupported ones.
- **Opinion fields** live together in one `opinion` object: `limitations_flagged` (≤3) and `deep_read {recommend, why}`. Structurally separate from the paper's claims, and labelled "Agent's opinion" as one block.
- **Absence is null, not unsupported.** `baselines` and `code_data` are nullable. Null means the paper has none, and nothing is shaded.
- **`key_equations`** are `{label | null, latex, meaning}`. **`key_figures`** are `{label, why}`.
- **List caps are soft.** The structured-output API drops `maxItems`, and the SDK would only enforce caps after the call is paid for. So Pydantic doesn't enforce max lengths: the prompt and the schema descriptions state the caps, and Verify trims an over-cap list with a warning. `min_length=1` on evidence and `key_results` stays enforced, since the API supports it.

**Grounding gap found, fixed two ways.** Some values carried parameters their own quotes don't contain, yet showed as supported. The invented-number check passed them, because the numbers appear elsewhere in the paper. Examples:
- `system` added m²=−4, the λ range and m_pL≈4;
- `baselines` added "tuned to 70% acceptance".

Two fixes:
1. A Read prompt rule: every number or parameter in a value must appear in that field's own quotes, or the field is `inferred`.
2. A Verify code check that numbers in each Fact value appear in that Fact's quotes, on top of the whole-paper check for `key_results`. Its tolerance and failure status go to [Code checks in Verify](06-verify-code-checks.md).

**Read prompt v1** is in `prompts/read/v1.md` on the branch, rule 1 above included.

**Request layout**, as SPEC §7.3 says: system (`prompts/shared/v1.md`) → user `[<paper>…</paper>` with a 5-minute `cache_control` breakpoint, then the rendered instructions`]`. The research questions go into the instructions, after the breakpoint, so the system-plus-paper prefix stays identical for M1's reviewer. Read keeps `effort: medium`: the Card is good without thinking, and the Golden eval can tune `read.effort` later.

**Prompt file convention**, for every `prompts/<stage>/<version>.md`:
- YAML front matter: `stage`, `version`, `system` (the shared prompt it pairs with), `model`, `effort`, `schema`, `params`, `notes`; then the body.
- Placeholders are `{{name}}`, filled by plain replacement, with an assert that none are left. `$`-templating crashes on LaTeX `$` in the prompt text.
- The shared system prompt is its own file (`prompts/shared/v1.md`) and must stay byte-identical across every call that reuses the cached prefix.
- Files are immutable once used.

**Lessons for the Verify ticket:**
- `loc` needs a mapping between canonical and raw offsets. The prototype's word-anchored search put R4 in "front matter", because `~\ref{…}` was removed by canonicalisation.
- A caption sentence repeated across three figures gave `match_count` = 3, as designed.

**Not tested:**
- a cache read (only one call was made);
- a refusal or fallback (the call ran with `fallbacks: "default"`);
- a PDF-sourced paper;
- any paper other than 1904.12072.

**Spec changes made:** SPEC §6, §7.3, §7.4, §8 and §12; GLOSSARY: Support and Opinion field.

**Assets:**
- branch `prototype/card-schema-read-prompt` (commit `a69c7c4`, never merged; local only, as there is no remote);
- the code in `.scratch/m0/prototypes/card-read/` on that branch;
- the Card in `out/card.json` and `out/card.md` on that branch, and the call's usage in `out/usage.json`. [Review page design](05-review-page-prototype.md) should build from `out/card.json`.

