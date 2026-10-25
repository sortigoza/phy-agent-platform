# Quote format: raw LaTeX or detexed prose?

Type: grilling
Status: open
Blocked by: —

## Question

Should Evidence quotes be taken from the raw flattened LaTeX source, or from detexed prose?

- **Raw LaTeX:** the verbatim check is exact, but quotes are ugly to read, so the UI has to render them with KaTeX.
- **Detexed prose:** easier to read, but the verbatim check then runs against detexed text, and detexing can lose information such as math and macros.

The answer fixes what `flattened.txt` is, what the Read prompt tells the model to quote, how Verify normalises, and how the review UI displays quotes. Also decide how `loc` (section or equation) is derived and checked.

## Context

Read first: the answer on [LaTeX flattening and detex tooling](02-latex-flattening-tooling.md), and its six trade-offs in `.scratch/m0/research/latex-flattening.md` on branch `research/latex-flattening`.
