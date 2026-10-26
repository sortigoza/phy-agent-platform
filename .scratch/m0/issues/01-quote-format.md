# Quote format: raw LaTeX or detexed prose?

Type: grilling
Status: resolved
Blocked by: —
Assignee: Saul

## Question

Should Evidence quotes be taken from the raw flattened LaTeX source, or from detexed prose?

- **Raw LaTeX:** the verbatim check is exact, but quotes are ugly to read, so the UI has to render them with KaTeX.
- **Detexed prose:** easier to read, but the verbatim check then runs against detexed text, and detexing can lose information such as math and macros.

The answer fixes what `flattened.txt` is, what the Read prompt tells the model to quote, how Verify normalises, and how the review UI displays quotes. Also decide how `loc` (section or equation) is derived and checked.

## Context

Read first: the answer on [LaTeX flattening and detex tooling](02-latex-flattening-tooling.md), and its six trade-offs in `.scratch/m0/research/latex-flattening.md` on branch `research/latex-flattening`.

## Answer

**Quote from raw flattened LaTeX.** `flattened.txt` is the raw output of the flattener. The model reads it and quotes from it, and Verify matches against it. Nothing detexed is stored. A detexed text would save only about $0.20–$1.30 a week, and it silently drops user macros, mangles numbers and loses `\label`s.

**PDF-only papers** become pypdfium2 plain text, saved as `flattened.txt` with `source_type=pdf`:
- soft hyphens (U+FFFE, U+00AD) are stripped, hyphenated line breaks joined, and NFKC applied;
- pages are separated by `\f`.

The model never sees the PDF itself.

**One matching contract for both source types.** `canonicalise(text, source_type)` runs identically on the quote and the source. A quote is found if canonical(quote) is a substring of canonical(source). The invented-number check reuses the same function. LaTeX rules:
- remove `\cite`, `\citep`, `\citet`, `\ref`, `\eqref` and `\label` with their arguments, including any `~` before them;
- map `\%`, `\&` and `\$` to `%`, `&` and `$`;
- unwrap `\emph{x}`, `\textit{x}`, `\textbf{x}` and `\text{x}` to `x`;
- map ` `` `, `''` and Unicode quotes to `"`, and Unicode dashes, `--` and `---` to `-`;
- map `~`, `\,`, `\ ` and `\;` to a space, then collapse whitespace;
- leave math otherwise as written (number tolerance belongs to the invented-number check, not to quote matching);
- match case-sensitively.

Every rule gets a unit test built from a real seed-paper snippet.

**Quote shape.** The Read prompt tells the model to copy quotes character for character, LaTeX included; the canonicaliser is a safety net, not permission to paraphrase. A quote:
- is one contiguous span, with no ellipses or stitching (a field that needs two passages gets two Evidence items);
- has 5–60 words after canonicalisation;
- may cross sentences but not paragraph or section boundaries.

A quote that breaks a rule is `unsupported`, the same as one that isn't found.

**`loc` is computed by Verify, not written by the model.** Verify reads it off the first match position:
- the enclosing section heading, detected from `\section`, `\subsection`, `\subsubsection`, `\paragraph`, `\appendix`, and preamble macros whose name or body contains `section` (this catches `\ssection` in 2003.06413);
- plus the `\label` key when the match is inside an equation, `figure` or `table` environment, for example `Sec. "Results" · fig:autocorr`;
- for PDF, the page, counted from `\f`.

Further rules:
- Equation numbers are not computed in M0.
- Evidence also stores `match_count`. A repeated quote stays `supported`, and the review page can show "also appears N× elsewhere".
- The old `loc` warning check goes away for Evidence. `key_equations` carry a `\label` key, which Verify checks exists.

**Display.** The review page renders math in quotes with KaTeX auto-render, fed the paper's preamble `\newcommand`s as `macros`. A server-side pass cleans up text markup for display only. Fragments that won't parse fall back to raw monospace. The final look belongs to [Review page design](05-review-page-prototype.md).

**Key figures, cheap version, in M0** (the Reader chose to bring this into scope):
- The model picks `key_figures: [{label, why}]` from the captions and `\label`s it already reads. It never sees pixels.
- Verify checks each label exists.
- Code resolves the label to its `\includegraphics` file in the downloaded tarball: PNG and JPG are served as they are, PDF figures are rendered to PNG with pypdfium2, and EPS shows "figure not renderable".
- PDF-sourced Cards have no figures.
- The field's shape and cap (≤ 3 suggested) go to [Card schema v1 and Read prompt v1](04-card-schema-and-read-prompt-prototype.md), the label check to [Code checks in Verify](06-verify-code-checks.md), and the display to [Review page design](05-review-page-prototype.md).

**Spec changes made:** SPEC §7.3, §7.4, §8 and §9; GLOSSARY: Evidence refined, Key figure added.

**Amended 2026-10-26** by [Keep, wire up or drop the verify.normalize knob](12-verify-normalize-knob.md): the minimum is now 5 words *or* 30 non-space canonical characters, and `canonicalise` gains six rules.
