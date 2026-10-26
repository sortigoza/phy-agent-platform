# /review: render a Card

Type: AFK
Status: done
Blocked by: 05

## Goal

`phy ui` serves `/review`, which renders the next verified Card the way the Review page design settled, read-only, along with the page conventions every later page reuses.

## Sources

SPEC §9 `/review` Layout and Page conventions, §8; [Review page design](../../m0/issues/05-review-page-prototype.md).

## Acceptance criteria

- `phy ui` starts FastAPI on `127.0.0.1:8000` (Jinja templates, HTMX, no build step); it never takes `phy.lock`.
- Shared base template: fixed top bar with nav (`/review`, `/monitor`, `/runs`), page subject, status badges, a row of section pills; the hover-help dictionary in one module used by every badge, pill and control; shared support and status colours.
- The top bar shows the Release badge from `release_status()` (amber "update available: vX (N commits)", hover lists commit subjects and `phy schedule update`). In this slice `release_status()` is a stub returning "none"; slice 11 implements it.
- Card rows in Card order: label with support and number pills, value, a (disabled) Flag button; inferred shaded blue, unsupported red; quotes folded under each value with `loc` and "also appears N× elsewhere"; ungrounded numbers highlighted; the Agent's opinion as one dashed block; stale and invented-number badges; warnings as grey chips on their sections.
- KaTeX auto-render (CDN, pinned version) fed the paper's preamble `\newcommand`s; text markup cleaned server-side for display only; `r` toggles raw LaTeX.
- Key figures resolved from the `\includegraphics` file in the source: PNG and JPG as they are, PDF rendered to PNG with pypdfium2 (cached next to the source), EPS as "figure not renderable".
- Ordering: verified Cards not yet reviewed, by `best_score` descending; Cards without a screening (`read --paper`) sort first.

## Tests first

- FastAPI `TestClient` against a seeded db with the recorded 1904.12072 Card: every field label present, shading classes match Support, quotes folded, `loc` text present.
- Preamble macro extraction from a synthetic preamble.
- Figure resolution: PNG, PDF→PNG, EPS fallback, missing file.
- Every hover key used in templates exists in the dictionary (a test scans templates).
- Ordering with and without screenings.

## Lift from

`origin/prototype/review-page:.scratch/m0/prototypes/review-page/` — `app.py`, `templates/base.html`, `templates/_macros.html`, `templates/variant_a.html` (layout A), `static/app.css`, `static/app.js`. Drop variants B and C.

## Not in this slice

Writes, timer and keys (07); `/runs`, `/monitor`, `/eval` pages.
