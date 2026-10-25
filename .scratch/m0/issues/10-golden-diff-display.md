# How the Golden run-to-run diff is shown

Type: grilling
Status: open
Blocked by: 05

## Question

How does `phy eval` show the run-to-run diff of Dev Cards against the last accepted run, so the Reader can review it before accepting a change? Decide:
- **Where:** CLI text, a page under `phy ui` (reusing the review page conventions), or both.
- **Granularity:** for each Card field, whether a change in its value, its quotes, its Support or its `loc` counts as a change; how list fields such as `key_results` are aligned between runs (by position or by matching values); and whether `opinion` changes are shown.
- **Noise:** which changes are suppressed as noise (rewording with the same Support?), given that the "Golden run-to-run diff" Instrument goes red on any change on Dev.

## Context

The Card shape is fixed by [Card schema v1 and Read prompt v1](04-card-schema-and-read-prompt-prototype.md). The example Card is `out/card.json` on branch `prototype/card-schema-read-prompt`. SPEC §10 (Scores) and §9 (Instrument table).
