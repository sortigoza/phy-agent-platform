# Card schema v1 and Read prompt v1

Type: prototype
Status: open
Blocked by: 01

## Question

What do the Card's Pydantic schema and the Read prompt v1 look like? Prototype both and run one real Read call on arXiv:1904.12072 using `claude-sonnet-5-5` with `output_config.format`, so the Reader can react to an actual Card. Questions to settle:
- **Fields:** their order, which are required, the maximum lengths of the lists, and how "inferred" Support is defined and shown.
- **Opinion fields:** how they are labelled.
- **Locations:** how `loc` is expressed.
- **Prompt layout:** how the prompt is laid out for caching (shared system prompt, then paper, then breakpoint, then instructions).
- **Prompt files:** the conventions every `prompts/<stage>/<version>.md` should follow.

Record the measured tokens and cost of the call.
