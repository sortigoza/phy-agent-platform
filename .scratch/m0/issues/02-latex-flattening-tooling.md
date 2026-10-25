# LaTeX flattening and detex tooling

Type: research
Status: claimed
Blocked by: —

## Question

What existing tooling should Read use to turn an arXiv `/src/` download into one text file the model reads and Verify checks against? Candidates include `latexpand`, `arxiv_latex_cleaner`, `pylatexenc` (LatexNodes2Text), `pandoc`, and a hand-rolled `\input`/`\include` inliner.

For each one, find out:
- How it handles the main-file search, nested `\input` and `\include`, `\newcommand` and `\def` macros, comments, appendices, `.bbl` files, and submissions that are broken or non-standard.
- Whether it can produce both raw-flattened output and detexed output (this feeds the quote format decision).
- Its install footprint (pure Python or a system binary) and its licence.
- How well it keeps section and equation labels, which are needed for `loc`.

Test against the real sources of the 4 seed papers (1904.12072, 2003.06413, 1606.02318, 1605.01735), fetched politely (≥ 3 s apart). Also cover PDF text extraction for the fallback (`pypdf` vs alternatives).
