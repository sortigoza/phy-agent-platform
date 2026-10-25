# Filter prompt v1 and its output schema

Type: prototype
Status: open
Blocked by: —

## Question

What do the Filter prompt v1 and its output schema look like? Prototype both, following the prompt file convention that [Card schema v1 and Read prompt v1](04-card-schema-and-read-prompt-prototype.md) set. Run them with `claude-haiku-5-5` at `effort: low` on the 4 seed papers plus a few out-of-scope abstracts that share keywords, so the Reader can react to real scores. Questions to settle:
- **Output schema:** `{Q1..Q4: {score, reason}}` as a Pydantic model; whether the score is a float 0–1 or a coarse scale, and how long the reason may be.
- **Score anchors:** what 0.5 and 0.9 mean (`filter.threshold`, `read.always_threshold`), and how the prompt anchors them.
- **Cache layout:** whether the system prompt plus the question definitions clear the model's minimum cacheable prefix, or whether a breakpoint there is wasted.
- **Rendering `questions.yaml`:** how it becomes prompt text, shared with how Read renders it.

Record the measured tokens and cost per Candidate.

## Context

SPEC §7.2. The prompt convention is `{{name}}` placeholders, YAML front matter, and a shared system prompt kept byte-identical (SPEC §7.3, Prompt files).
