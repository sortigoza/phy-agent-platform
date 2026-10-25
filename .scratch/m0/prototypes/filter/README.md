# PROTOTYPE: Filter prompt v1 and its output schema (throwaway)

Answers the M0 map ticket "Filter prompt v1 and its output schema". Not production code.

```sh
set -a; . ../card-read/.env; set +a                 # ANTHROPIC_API_KEY (or ant auth login)
../card-read/.venv/bin/python score.py --dry-run    # token counts only
../card-read/.venv/bin/python score.py --runs 2     # live: both variants × 10 papers × 2 runs (~$0.006)
```

- `questions.yaml`: stand-in for `$PHY_HOME/questions.yaml`, plus the new `scope_notes`.
- `questions.py`: `render_questions()` and `render_scope_notes()`, the one renderer shared with Read.
- `prompts/filter/v1a.md`: float 0–1 with anchors (**chosen; it becomes `prompts/filter/v1.md`**).
- `prompts/filter/v1b.md`: integer 0–4 enum (rejected).
- `papers.json`: the 4 seed Papers plus 6 probes (arXiv API metadata); `out/*.jsonl`: every call.

## Results (claude-haiku-5-5, effort low, 2026-10-25)

Best score, run 0 / run 1:

| Paper | Kind | A (float) | B (0–4) |
|---|---|---|---|
| 1904.12072 Albergo et al. | seed | Q1 0.95 / 0.95 | Q1 4 / 4 |
| 2003.06413 Kanwar et al. | seed | Q1 0.95 / 0.9, Q3 0.9 / 0.85 | Q1 4, Q3 4 |
| 1606.02318 Carleo & Troyer | seed | Q2 0.9 / 0.95 | Q2 4 / 4 |
| 1605.01735 Carrasquilla & Melko | seed | Q4 0.95 / 0.95 | Q4 4 / 4 |
| 1410.3831 Mehta & Schwab | borderline | Q4 0.3 / 0.3 | Q4 1 / **2** |
| 1602.07576 G-CNN | ML only | Q3 0.2 / 0.3 | Q3 **2 / 2** |
| 1807.03039 Glow | ML only | Q1 0.3 / 0.15 | Q1 1 / 1 |
| 2002.12347 BMW muon g-2 | lattice, no ML | ≤ 0.1 | 0 |
| 1709.06680 Deep Lattice Networks | "lattice" in an ML sense | 0.1 | 1 |
| 1910.11333 Quantum supremacy (SI) | hardware | ≤ 0.05 | 0 |

- **A** clusters at the anchors anyway, drifts ≤ 0.15 between runs, and kept every probe at or below the scope cap (0.3). Reasons were ≤ 19 words.
- **B** makes the 0.5 threshold a one-step cliff (Mehta & Schwab flipped across it between runs) and broke its own scope cap on G-CNN twice. 3 of its reasons ran over 20 words.
- **Cache:** the system prompt is 854 tokens; with the schema the cached prefix is 1,347 tokens, which clears Haiku 5.5's 512 minimum. The first call wrote it, and all 19 later calls read it.
- **Cost:** cold $0.00031, warm **$0.00015 per Candidate** (about 300 tokens in and 220 out, the output including thinking), about 2.3 s per call. At `alerts.candidates_range` [100, 400] a week, Filter costs under $0.07 a week.

The verdict and the decisions are in the ticket.
