# Filter prompt v1 and its output schema

Type: prototype
Status: resolved
Blocked by: —
Assignee: Saul

## Question

What do the Filter prompt v1 and its output schema look like? Prototype both, following the prompt file convention that [Card schema v1 and Read prompt v1](04-card-schema-and-read-prompt-prototype.md) set. Run them with `claude-haiku-5-5` at `effort: low` on the 4 seed papers plus a few out-of-scope abstracts that share keywords, so the Reader can react to real scores. Questions to settle:
- **Output schema:** `{Q1..Q4: {score, reason}}` as a Pydantic model; whether the score is a float 0–1 or a coarse scale, and how long the reason may be.
- **Score anchors:** what 0.5 and 0.9 mean (`filter.threshold`, `read.always_threshold`), and how the prompt anchors them.
- **Cache layout:** whether the system prompt plus the question definitions clear the model's minimum cacheable prefix, or whether a breakpoint there is wasted.
- **Rendering `questions.yaml`:** how it becomes prompt text, shared with how Read renders it.

Record the measured tokens and cost per Candidate.

## Context

SPEC §7.2. The prompt convention is `{{name}}` placeholders, YAML front matter, and a shared system prompt kept byte-identical (SPEC §7.3, Prompt files).

## Resolution

Prototyped two variants with `claude-haiku-5-5` at `effort: low` on the 4 seed Papers plus 6 keyword-sharing probes, two runs each. The code and every call are on branch `prototype/filter-prompt` (`.scratch/m0/prototypes/filter/`, with the results table in its README).

**Output schema.** One field per question id in `questions.yaml`, `{Qn: {reason, score}}`, built as a Pydantic model from the ids, so adding a question changes no code. Adding a question does change the cached prefix and the `scores_json` keys, and old screenings keep theirs. `reason` comes before `score` (the same order as quotes before value in the Card) and is one line of at most 20 words.

**Score: float 0–1, anchored.** The integer 0–4 enum was rejected: it made 0.5 a one-step cliff (Mehta & Schwab flipped across it between runs) and screened in G-CNN against its own scope cap. The float clusters at the anchors anyway and drifted ≤ 0.15. Structured outputs can't enforce `minimum`/`maximum`, so code clamps to [0, 1] and logs a warning rather than failing a paid call.

**Anchors** (in the prompt; the thresholds are their config twins):
- **0.9+** (`read.always_threshold`): the main contribution answers the question directly. Keep it for clear cases.
- **0.7**: on the topic, but a narrower or neighbouring aspect.
- **0.5** (`filter.threshold`): something someone working on the question would use, though the paper's focus is elsewhere.
- **0.3**: same field or a shared technique, nothing new for the question. Mehta & Schwab's RG–deep-learning mapping belongs here: the Reader confirmed it should not be Screened in.
- **0.1**: shared words only.
- A paper under a scope note scores at most 0.3 on every question.

**Cache layout.** The Filter prompt is its own whole system prompt (`system: self`), not the Read shared prompt, because that prompt describes a full paper text. Its cache breakpoint is worth having: 854 tokens of system prompt plus the schema make a 1,347-token cached prefix, above Haiku 5.5's 512 minimum. The first call wrote it and every later call read it. The user turn is the title, arXiv categories and abstract.

**Rendering `questions.yaml`.** `render_questions()` (in `src/phy/questions.py`, shared with Read) renders `- Qn. Title: description` in file order, with the description's whitespace collapsed. It is deterministic, so the cached prefix stays byte-identical. Keywords are never rendered: they drive the code pre-filter, and showing them would make the model score on word overlap. A new top-level `scope_notes` list carries the SPEC's prose "negative keywords", which only a model can apply ("lattice used only in an ML sense"), and `render_scope_notes()` fills `{{scope_notes}}`. Literal `negative_keywords` stay code-only.

**Measured.** About 300 input tokens per Candidate beyond the cached prefix, about 220 output tokens (thinking included), about 2.3 s. Cold $0.00031, warm **$0.00015 per Candidate**, so under $0.07 a week at 400 Candidates. Seeds scored 0.9–0.95 on their question and every probe ≤ 0.3, so precision in the Filter decision is in good shape on this small set.

SPEC §4 (Out of scope), §6 (`questions` module, `questions.yaml`), §7.2 and §7.3 and the QUICK_START `questions.yaml` example are updated to match.

The 6 probes (Glow, G-CNN, Deep Lattice Networks, quantum supremacy, BMW muon g-2, Mehta & Schwab) are ready-made `out_of_scope_probe` Papers for the Golden set's Filter-decision metric.
