# How the Golden run-to-run diff is shown

Type: grilling
Status: resolved
Blocked by: 05
Assignee: Saul

## Question

How does `phy eval` show the run-to-run diff of Dev Cards against the last accepted run, so the Reader can review it before accepting a change? Decide:
- **Where:** CLI text, a page under `phy ui` (reusing the review page conventions), or both.
- **Granularity:** for each Card field, whether a change in its value, its quotes, its Support or its `loc` counts as a change; how list fields such as `key_results` are aligned between runs (by position or by matching values); and whether `opinion` changes are shown.
- **Noise:** which changes are suppressed as noise (rewording with the same Support?), given that the "Golden run-to-run diff" Instrument goes red on any change on Dev.

## Context

The Card shape is fixed by [Card schema v1 and Read prompt v1](04-card-schema-and-read-prompt-prototype.md). The example Card is `out/card.json` on branch `prototype/card-schema-read-prompt`. SPEC §10 (Scores) and §9 (Instrument table).

## Answer

**Baseline.** A run is accepted explicitly: `eval_runs.accepted_at` is set by `phy eval accept <id>`. The baseline of a run is the latest accepted run with the same `golden_version`. With no baseline (the first eval, or a new Golden set version) the run shows "no baseline", and accepting it makes it the baseline.

**Accepting.** `phy eval accept <id>` refuses when the run's prompt versions and model don't match the active `config.toml` (the Reader switches config first, then accepts, so the baseline is always what's live), and when the run has a hard fail (any invented number, or grounding below 98%). There is no `--force`. Accept never edits config. Material changes don't block it: they are what the Reader reviews. The page shows the accept command; there is no button.

**Storage.** Each eval Card is stored whole in `eval_runs.per_paper_json`, never in `cards`, so eval Cards stay out of the review queue and the production Instruments. `phy eval` computes the diff when it runs and stores `baseline_id`, `diff_json` and `material_changes` on the run, so an old diff stays as it was shown.

**Where.** Both. The CLI prints a short summary: Scores against the baseline, material changes and rewordings per Paper, and the URL. The full diff is on `/eval/<id>` under `phy ui`, with the review page conventions: top bar, one section pill per Paper, fields in Card order, hover help from the shared dictionary.

**Material change vs rewording**, per Card field:
- **Material** (counts toward red): Support changed; the field's set of parsed numbers changed (Verify's parser, by value plus significant figures); an invented number appeared; a quote now fails; a list item added or removed; `code_data` flipped between null and present; a Filter decision crossed `filter.threshold` or `read.always_threshold`.
- **Rewording** (shown greyed out and folded, never red): the value text changed with the same numbers and Support; different quotes chosen that still pass; Filter score drift that stays on the same side of both thresholds.
- **Ignored:** `loc` and `match_count`, because Verify derives them.

**Lists** (`key_results`, `assumptions`, `limitations_stated`, `key_equations`, `key_figures`, `questions`) are paired by content, not position: items sharing numbers first, then by `difflib` ratio above about 0.5. Unmatched items are added or removed. Reordering alone is ignored.

**Opinion** changes (`limitations_flagged`, `deep_read`) sit in their own folded section and never count toward red. A `deep_read.recommend` flip is highlighted.

**Filter.** The page header shows each Q1–Q4 score as baseline → new.

**Rendering.** A changed value shows old and new stacked, rendered with KaTeX, with a toggle to a word-level ins/del diff of the raw text (an inline diff inside KaTeX markup breaks rendering).

**Instrument tile.** "Golden run-to-run diff" shows the latest eval's `material_changes`. It is red when that count is above 0 and the run is unaccepted, grey with no baseline, and links to `/eval/<id>`. A run left unaccepted keeps the tile red until the next eval replaces it. The SPEC §9 red condition is now "any material change on Dev".

Updated: `docs/SPEC.md` §6 (`eval_runs`), §9, §10; `QUICK_START.md` §8; `GLOSSARY.md` (Run-to-run diff, Material change, Accepted run).
