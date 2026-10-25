# Review page design

Type: prototype
Status: resolved
Blocked by: 04
Assignee: Saul

## Question

Can a Card be reviewed in about 4 minutes on the `/review` page? Build a rough FastAPI + HTMX page from the prototype Card that shows:
- the tl;dr, results and assumptions first;
- unsupported fields shaded;
- quotes that expand;
- the Stale and invented-number badges;
- relevance, deep read, and a per-field Flag (a kind plus an optional note);
- key figures, resolved from the tarball (PDF figures rendered to PNG; EPS shows "not renderable");
- quotes rendered from raw LaTeX: KaTeX for math with the preamble macros, a server-side cleanup of text markup, and a raw fallback;
- the derived `loc`, and "also appears N× elsewhere" when `match_count` > 1;
- a timer.

Settle the layout, how Flags are entered, keyboard shortcuts, and the page conventions that `/monitor` and `/runs/<id>` will reuse.

## Context

Build from the real prototype Card, `out/card.json` on branch `prototype/card-schema-read-prompt` (the source is in `src_1904.12072/` there, gitignored, and needs a re-download). From [Card schema v1 and Read prompt v1](04-card-schema-and-read-prompt-prototype.md):
- Support has three states to shade: supported, `inferred` (its own shading) and unsupported;
- the `opinion` object is shown as one "Agent's opinion" block;
- a null `baselines` or `code_data` means "none" and is not shaded.


## Answer

**Variant A (Document) wins, with C's section bar added.** The Reader tried three layouts on the real Card, built with the demo states it lacks: A one column, B a split pane, C a step-by-step triage deck. They preferred A, plus a section nav like C's stepper. The Reader approved the Flag entry, the keys and the shared top bar as built. No review time was logged.

**`/review` layout (A):**
- **Order:** one column in Card order, which is also generation order: Summary (tl;dr, results, assumptions), Setup (system, method, baselines, claimed advance, code/data), Limitations, Equations & figures, Agent's opinion.
- **Fields:** each field is a row with its label on the left (support and number pills wrap under the label), the value in the middle and a ⚑ button on the right.
- **Shading:** inferred is blue, unsupported is red, and supported is unshaded. Null `baselines` and `code_data` show "none" and are not shaded.
- **Quotes:** folded under each value in a "N quotes" disclosure. Each quote shows the derived `loc` and, when `match_count` > 1, "also appears N× elsewhere". A quote Verify couldn't find says so in red.
- **Equations:** `$$…$$` display math with their meaning. **Figures:** the PNG renders inline with the `why` text, and the caption collapses. An EPS figure shows "figure not renderable".
- **Agent's opinion:** one dashed block that says it is the agent's judgement.
- **Verdict bar:** fixed to the bottom of the screen, with relevance y/p/n, deep read (showing the agent's suggestion), a note and save.

**Flags.** ⚑ or `f` opens an inline form under the field. Keys `1`–`4` pick the kind while the note is still empty, Enter saves and Esc cancels. Saved Flags show as chips on the field, each with a × to remove it.

**Keys** (`?` shows them): `j`/`k` field, `[`/`]` section, `o` quotes, `f` Flag, `y`/`p`/`n` relevance, `d` deep read, `s` save, `r` raw LaTeX everywhere.

**Page conventions for `/monitor` and `/runs/<id>`:**
- **Top bar:** fixed to the top. It holds the nav (review · monitor · runs), the subject (here: id, version, authors, title), status badges and the page's live number (here: the timer). A row of section pills under it highlights the current section and jumps on click or `[`/`]`.
- **Hover help:** every badge, pill, control and Flag kind has a `title` explaining it, written for a new user. The text lives in one `HELP` dict, so a thing is explained the same way on every page.
- **Shared look:** status and support colours and pill shapes; HTMX for writes, with out-of-band swaps for anything else on the page that changes; `?` for a key overlay; `r` for raw LaTeX wherever LaTeX is shown.

**LaTeX rendering held up:**
- the preamble `\newcommand`s, read by a small parser, work as KaTeX macros (`\paren`, `\netp`, `\expt` with `\underset`);
- the server-side cleanup handles `{\it …}`, `\emph`, `\textbf`, `~`, `\ref`, `\cite` (shown as small `ref` / `cite` markers), dashes and quotes, and leaves unknown commands raw;
- with `throwOnError: false`, a KaTeX error shows the raw source in red.

**Figures:** labels are resolved by scanning `figure` environments in the flattened tex for `\label` and `\includegraphics`, then trying the file name with `""`, `.pdf`, `.png`, `.jpg` and `.eps`. A PDF page is rendered with pypdfium2 at about 1100 px wide, which needs Pillow. All 12 PDFs in the 1904.12072 tarball rendered.

**Card content: two Read prompt v2 rules.** The Reader's feedback was about the Card text, not the page:
1. Expand every acronym the first time the Card uses it, in field order, e.g. "Markov chain Monte Carlo (MCMC)".
2. Name the authors as "Surname et al." (both surnames when there are two), never "the authors". The author list comes from the OAI-PMH metadata through a `{{authors}}` placeholder.

v1 is immutable once used, so these go into v2. The authors also show in the top bar.

**Timer:** the top bar shows a client-side clock for the Reader, amber at 4:00 and red at 5:00. The stored `seconds_spent` stays server-side, from render to submit, as in SPEC §9.

**Not tested:**
- a timed review pass;
- the "next Card" flow and the Markdown export, since the prototype has only one Card;
- a PDF-sourced Card;
- a Card with real unsupported fields: they were demo overlays.

**Spec changes made:** SPEC §9 (`/review` layout, keys, hover help, page conventions) and §7.3 (Read prompt v2 rules).

**Assets:** branch `prototype/review-page` (commit `9c2a4e3`, never merged, pushed to `origin`); the code is in `.scratch/m0/prototypes/review-page/` (`.venv/bin/python app.py`, `/review?variant=A|B|C`, `&demo=0` for the real Card).
