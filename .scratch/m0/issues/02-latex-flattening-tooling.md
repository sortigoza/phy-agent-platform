# LaTeX flattening and detex tooling

Type: research
Status: resolved
Blocked by: —

## Question

What existing tooling should Read use to turn an arXiv `/src/` download into one text file the model reads and Verify checks against? Candidates include `latexpand`, `arxiv_latex_cleaner`, `pylatexenc` (LatexNodes2Text), `pandoc`, and a hand-rolled `\input`/`\include` inliner.

For each one, find out:
- How it handles the main-file search, nested `\input` and `\include`, `\newcommand` and `\def` macros, comments, appendices, `.bbl` files, and submissions that are broken or non-standard.
- Whether it can produce both raw-flattened output and detexed output (this feeds the quote format decision).
- Its install footprint (pure Python or a system binary) and its licence.
- How well it keeps section and equation labels, which are needed for `loc`.

Test against the real sources of the 4 seed papers (1904.12072, 2003.06413, 1606.02318, 1605.01735), fetched politely (≥ 3 s apart). Also cover PDF text extraction for the fallback (`pypdf` vs alternatives).

## Answer

**Flattener: write our own.** About 100 lines of stdlib Python. It:
- finds the main file from the `00README` toplevel declaration, falling back to the uncommented `\documentclass` file;
- inlines `\input` and `\include` recursively, both braced and brace-less;
- strips `%` comments, `comment` environments, `\iffalse` blocks, and anything after `\end{document}`;
- drops `thebibliography` and `\bibliography` but keeps what follows them (1606.02318 puts its whole appendix after the bibliography).

A prototype matched `latexpand` on all 4 seed papers apart from whitespace, and kept every `\label`. `latexpand` (BSD-3) serves only as a test reference: it needs Perl and TeX Live, and it keeps inline bibliographies, comment environments and `\iffalse` blocks.

**Rejected tools:**
- `pandoc`: GPL and 114 MB. It fails on brace-less `\input`, drops captions, and chokes on user macros.
- `pylatexenc`: silently drops user macros and loses most labels.
- `arxiv_latex_cleaner`: doesn't inline `\input` at all. Its comment-removal rules are worth copying.

**PDF fallback: `pypdfium2`.** It's Apache-2.0/BSD-3, 7.6 MB, fast, and resolves ligatures. Soft hyphens come out as U+FFFE and must be stripped. `pypdf` is second choice, since it sometimes merges words. PyMuPDF is ruled out: it's AGPL and large.

**Facts for later tickets:**
- **Seed sources:** all 4 seed sources are gzip then tar, each with a single `.tex` file. Nested inputs were tested only on a synthetic fixture.
- **Section macros:** 2003.06413 uses a custom `\ssection` macro, so checking `loc` must not assume `\section`.
- **Equation numbers:** these aren't in the source, only `\label`s are.
- **Size:** raw LaTeX is about 20–24% larger than detexed text.

**Input to the quote format decision:** the research recommends storing raw flattened LaTeX as the canonical `flattened.txt` and deriving any detexed view from it. Raw quotes need a shared normaliser for `~\cite`, `\%`, math and user macros, applied identically to quote and source, and PDF text goes through the same path. A hybrid is possible: the model quotes raw text and the UI renders it detexed. The six trade-offs are in the findings file.

**Spec changes made:** SPEC §7.3, covering the flattener rules and the PDF library.

**Assets:**
- branch `research/latex-flattening` (commit `1f92807`, never merged);
- the findings at `.scratch/m0/research/latex-flattening.md` on that branch.
