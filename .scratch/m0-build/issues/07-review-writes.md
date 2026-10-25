# /review: Reviews and Flags

Type: AFK
Status: open
Blocked by: 06

## Goal

The Reader can review a Card end to end: relevance, Flags, deep read, save, timed, keyboard-driven. This slice meets the first M0 exit criterion.

## Sources

SPEC §6 `reviews`/`flags`, §9 `/review` Controls / Keys / Timing / Export; QUICK_START §3 and `phy flags`; [Review page design](../../m0/issues/05-review-page-prototype.md).

## Acceptance criteria

- Migration `004_reviews_flags` creates `reviews` and `flags`.
- Relevance (`y`/`p`/`n`), deep read (`d`) and save (`s`) in the fixed bottom bar, written with HTMX; saving sets the Card status `reviewed` and loads the next Card.
- Flags inline: `f`, then `1`–`4` for the kind, optional note, Enter; Flags show as chips on the field and can be removed before save.
- Keys `j`/`k`, `[`/`]`, `o`, `r`, `?` as in SPEC; `?` lists them from the hover dictionary.
- Server-side timer from render to submit stored as `seconds_spent`; the top-bar clock turns amber at 4:00 and red at 5:00.
- "Export to Markdown" downloads the Card with its Review.
- `phy flags --since 30d` prints Flags grouped by field and kind.
- QUICK_START §3 smoke test works as written on a real `$PHY_HOME` (`read --paper 1904.12072`, `verify`, `ui`), except `golden add`, which arrives in slice 13.

## Tests first

- Saving a Review writes one row with relevance, deep read and `seconds_spent` from a faked clock; the Card becomes `reviewed`; the response renders the next Card.
- Flag create and delete; kind validation; note optional.
- Markdown export contains every field value and the Review.
- `phy flags` grouping on seeded rows.

## Lift from

`origin/prototype/review-page:.scratch/m0/prototypes/review-page/` — `templates/_flag_chips.html`, `templates/_saved.html`, the key handling in `static/app.js`.

## Not in this slice

Review-time and relevance tiles (16).
