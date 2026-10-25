# Card schema v1 and Read prompt v1

Type: prototype
Status: open
Blocked by: 01

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
