# Run-to-run diff and eval accept

Type: AFK
Status: open
Blocked by: 06, 14

## Goal

Every eval run is diffed against the accepted baseline into Material changes and rewordings, shown on `/eval/<id>`, and `phy eval accept` makes a run the new baseline.

## Sources

SPEC §10 The run-to-run diff / Accepting a run; [How the Golden run-to-run diff is shown](../../m0/issues/10-golden-diff-display.md).

## Acceptance criteria

- Baseline: the latest accepted run with the same `golden_version`; none → "no baseline".
- Field-level diff; lists paired by content (shared numbers first, then text similarity), reordering ignored; `loc` and `match_count` ignored.
- Material: Support changed, set of parsed numbers changed (value plus significant figures), invented number appeared, a quote now fails, list item added or removed, `code_data` null↔present, a Filter decision crossed `filter.threshold` or `read.always_threshold`. Everything else is a rewording. Opinion changes go in their own section and never count; a deep-read flip is highlighted.
- `diff_json`, `material_changes` and `baseline_id` stored; the CLI summary prints Scores vs baseline, Material changes and rewordings per Paper, and the `/eval/<id>` link.
- `/eval/<id>`: page conventions; Material changes red, rewordings greyed and folded; old over new rendered with KaTeX, toggle to a word-level raw diff.
- `phy eval accept <id>` sets `accepted_at`; refuses when prompt versions or model differ from the active config, or on a hard fail (invented number, grounding < 95%; the Grounding tile on `/monitor` still goes red below 98%, from [Amend the M0 cut](../../m0/issues/20-amend-m0-cut.md)); no override; never edits config.

## Tests first

- Diff classification table: one case per Material rule and per rewording rule.
- List pairing: reordered list → no change; one item removed → Material.
- Baseline selection across Golden versions.
- `accept` refusals: config mismatch, invented number, grounding 97%.
- `/eval/<id>` renders red and folded sections.

## Lift from

Nothing beyond the page conventions from 06.

## Not in this slice

The Golden diff tile (16).
