# Research: LaTeX flattening, detex and PDF fallback tooling

Ticket: [LaTeX flattening and detex tooling](../issues/02-latex-flattening-tooling.md). Date: 2026-10-25.
Context: SPEC §7.3 (Read: fetch, magic-byte detection, flatten into `flattened.txt`) and §7.4 (Verify: verbatim quotes, invented numbers, `loc`).

## Recommendation (short)

1. **Write our own flattener in Python** (about 100 lines, stdlib `re` only). Use `latexpand` only as a test oracle in development. Do not make it a runtime dependency.
2. **Store the raw flattened LaTeX as `flattened.txt`.** This is the canonical text the model reads and Verify checks against. A detexed view, if the quote-format ticket wants one, should be derived from it and never replace it.
3. **Do not use pandoc or arxiv_latex_cleaner in the pipeline.** Borrow the cleaner's comment-removal rules and reimplement them.
4. **PDF fallback: `pypdfium2`** (Apache-2.0/BSD-3, prebuilt wheel). `pypdf` (BSD-3, pure Python) is the second choice. Avoid PyMuPDF because of its AGPL licence and a heavy 2.0 dependency tree.

## Method

- Downloaded `https://arxiv.org/src/<id>` for the 4 seed papers, 4 s apart, to the session scratchpad (not the repo).
- All four came back `Content-Type: application/gzip`. Magic bytes were `1f 8b`, and after gunzip the bytes at 257 read `ustar`, so every one was **gzip then tar**.
- Also fetched 2 PDFs from `arxiv.org/pdf/<id>`, again 4 s apart. They start `%PDF-`.
- Ran each candidate on each paper, plus a synthetic fixture to exercise the edge cases the seed papers lack.
  - The fixture covers: nested `\input{a}` → `\input{b}`, brace-less `\input sections/method.tex`, `\include`, `comment` env, `\iffalse`, a trailing `%` comment, text after `\end{document}`, a stray second `\documentclass` file, and a `.bbl`.
- Tools were installed into a throwaway venv (Python 3.13). uv was not installed, so `python -m venv` was used. Versions: latexpand 1.7.2 (from MacTeX), arxiv_latex_cleaner 1.0.11, pylatexenc 2.11, pandoc 3.9 (via `pypandoc_binary` 1.17), pypdf 6.21.2, pypdfium2 5.14.0, pdfminer.six 20260107, PyMuPDF 2.0, poppler `pdftotext`.

## What the seed sources actually look like

| Paper | Files | Main | `\input`/`\include` | User macros | Comments | Bibliography | Appendix | `\label`s |
|---|---|---|---|---|---|---|---|---|
| 1904.12072 | `main.tex` + `main.bbl` + figs | `main.tex` | none | 9 `\newcommand`, 2 `\DeclareMathOperator`, `\mathbbm` | 76 full-line | `\bibliography{FlowGenBib}`; the `.bbl` is named after the main file, not the `.bib` | `\appendix` before bib | 31 |
| 2003.06413 | `main.tex` + `main.bbl` | `main.tex` | none | 12 `\newcommand`, incl. **`\ssection` used instead of `\section`** (PRL run-in heads); `\let\Re\undefined` | 15 | `\bibliography{main}` | none | 10 |
| 1606.02318 | `nqs_arxiv.tex` | `nqs_arxiv.tex` | none | LyX-generated preamble | 4 | **inline `thebibliography`**, and **the appendix comes after it** (l. 469–795 bib, l. 799 `\appendix`) | after bib | 23 |
| 1605.01735 | `machine.tex` | `machine.tex` | none | `\def\bea`, `\newcommand{\beq}` env-shortcut macros | 12 | inline `thebibliography` | before bib | 10 |

Takeaways:

- **None of the 4 uses `\input`.** All are single-file, so nested inputs are tested only by the fixture.
- **Main file:** in all 4 it is the only `.tex` file and contains `\documentclass`.
  - arXiv's own rule: a `00README.json` / `00README.XXX` can declare `toplevel` files. Without one, arXiv uses the heuristic "only one LaTeX file contains `\documentclass`", and since April 2024 it ignores extra `\documentclass` files ([00README help](https://info.arxiv.org/help/00README.html)).
  - Compilation is always from the submission root, so `\input` paths resolve relative to the root ([submit_tex help](https://info.arxiv.org/help/submit_tex.html)).
  - A precompiled `.bbl` must be named after the main `.tex` ([same page](https://info.arxiv.org/help/submit_tex.html)). This is why 1904.12072 has `main.bbl` but `\bibliography{FlowGenBib}`.
- **"Drop the bibliography" must not mean "truncate at the bibliography".** 1606.02318 puts its whole appendix (5 sections, 9 labelled equations) after `thebibliography`.
- **Section headings are not always `\section`.** 2003.06413 has zero `\section` commands and uses `\newcommand{\ssection}[1]{\emph{#1.---}}`. A `loc` check that only knows `\section` will reject every section `loc` on PRL-style papers.
- Lots of inline markup appears mid-sentence: 96 `~\cite`, 58 `~\ref`, 13 `\eqref`, 36 `\%`, `\emph{...}`, `\"{o}`. This decides how verbatim quotes can be matched (see the open trade-offs).

## Results per tool

| | Hand-rolled inliner | latexpand | arxiv_latex_cleaner | pylatexenc `LatexNodes2Text` | pandoc (LaTeX → plain/markdown) |
|---|---|---|---|---|---|
| Role | flatten | flatten | clean only; **does not inline** | detex | parse + convert (also inlines) |
| Main-file detection | yes (ours: `\documentclass` + `\begin{document}`, largest wins, others logged; should also honour `00README`) | no; caller names the file | no; whole folder | n/a | no; caller names the file |
| Nested `\input`/`\include` | yes (fixture: 2 levels, brace-less, `\include`) | yes, all fixture cases; adds `\clearpage{}` around `\include` | **no**, leaves `\input` in place | n/a | braced only; **hard error (exit 64) on brace-less `\input file.tex`** |
| `%` comments | yes (respects `\%`) | yes; also drops everything after `\end{document}` | yes, incl. after `\end{document}` | n/a | yes |
| `comment` env / `\iffalse` | yes (simple non-nested regex) | **no**, both kept | **yes** (also `\if0`, configurable) | n/a | `\iffalse` handled; `comment` env depends |
| User macros | kept verbatim | kept (`-d` can replace by hand) | kept | **unknown macros silently dropped**: `$\Uone$` → "a  gauge group" in 2003.06413 | expanded (`latex_macros`); but `\let\Re\undefined` → `\undefined` in output; `\mathbbm`, `\small` in math fail → raw TeX |
| Appendices | kept, incl. after bib | kept | kept | kept | kept |
| `.bbl` / bibliography | dropped (`thebibliography` env and `\bibliography{}`) | inline `thebibliography` **kept** (2 of 4 papers); `--expand-bbl FILE` inlines a `.bbl` | deletes `.bib` files | n/a | inline bib kept in markdown |
| Labels kept (1904 / 2003 / 1606 / 1605) | 31/31, 10/10, 23/23, 10/10 | same | same | default: 3, 0, 0, 0; `math_mode='verbatim'`: 10, 6, 17, 0 | plain: 9, 5, 16, 0; markdown: 28, 10, 23, 10 |
| Figure captions | kept | kept | kept | kept | **plain drops captions** (0 of 3 "configurations from the HMC" captions in 1904.12072); markdown keeps 1 of 3 |
| `\ref`/`\cite` | kept | kept | kept | `<ref>`, `<cit.>` placeholders | resolved to text or dropped |
| Output size, 1904.12072 (chars) | 57,094 | 57,105 | — | 46,560 | 45,114 / 55,924 |
| Speed per paper | ~3 ms | ~30 ms (Perl start) | ~1 s | ~0.1 s | ~0.3 s |
| Footprint | stdlib | Perl script in TeX Live (713 lines); not on a bare Mac | Python + absl-py, Pillow, PyYAML, regex | pure Python, 1.1 MB, no deps | 114 MB native binary (`pypandoc_binary`) or system pandoc |
| Licence | ours | BSD-3 ([CTAN](https://ctan.org/pkg/latexpand)) | Apache-2.0 ([GitHub](https://github.com/google-research/arxiv-latex-cleaner)) | MIT ([PyPI](https://pypi.org/project/pylatexenc/)) | GPL-2.0-or-later ([GitHub](https://github.com/jgm/pandoc)) |

Notes:

- On the 4 real papers, hand-rolled and latexpand output differ only in whitespace and in the `\bibliography...` lines.
  - latexpand removes a `%` comment and its newline together, as TeX does, so `}%\n\subfloat` becomes `}\subfloat`.
- latexpand's documented limitation is only `\includeonly` ([CTAN](https://ctan.org/pkg/latexpand)). It is a sound reference implementation, but it is Perl plus TeX Live, and it needs a post-pass anyway for `thebibliography`, the `comment` env and `\iffalse`.
- arxiv_latex_cleaner only cleans; it never merges files into one ([README](https://github.com/google-research/arxiv-latex-cleaner)).
  - Its comment rules are worth copying: `comment` env, `\iffalse`/`\if0`, and treating every `\if...` as a conditional unless excepted.
  - It writes a copied folder `<dir>_arXiv` next to the input, which is awkward for a pipeline.
  - On the fixture it kept the stray `notes.tex`, since root-level `.tex` files are never treated as unused.
- pylatexenc `math_mode` takes `fancy` (default), `text`, `with-delimiters`, `verbatim` or `remove`. Refs and cites become `<ref>` and `<cit.>` placeholders ([docs](https://pylatexenc.readthedocs.io/en/latest/latex2text/)).
  - User macros must be registered by hand through `latex_context_db`, otherwise their output is silently lost. This happened to `\Uone` (U(1)) and drove every label count to 0.
- Pandoc is the worst fit. It is GPL and native, it fails hard on valid TeX that latexpand handles (brace-less `\input`), it drops captions in plain output (results often live in captions), and it emits HTML `<span>`/`<figure>` in markdown output.

## PDF fallback (2003.06413 and 1606.02318)

Each tool was checked against 5 probe phrases per paper, after normalising text with NFKC, joining hyphenated line breaks and collapsing whitespace.

| Tool | Licence | Footprint | Probes found | Time per paper | Notes |
|---|---|---|---|---|---|
| **pypdfium2** | Apache-2.0 / BSD-3 (PDFium) | 7.6 MB wheel, no deps | 10/10 | 0.1–0.5 s | Ligatures already resolved. Soft hyphens appear as U+FFFE (`configura￾tion`), so strip U+FFFE and U+00AD. |
| pypdf | BSD-3 | 3.9 MB, pure Python, no deps | 10/10 | 0.8–1.1 s | Some spaces lost (`linksUµ(x)`), which breaks quotes across them. `ﬁ` ligatures (fixed by NFKC). Warnings on form XObjects. |
| pdfminer.six | MIT | 9.3 MB + cryptography | 10/10 | 0.5–3.5 s | Emits `(cid:101)` for unmapped glyphs. Slowest. |
| PyMuPDF 2.0 | **AGPL-3.0** or commercial ([docs](https://pymupdf.readthedocs.io/en/latest/about.html)) | 110 MB, and 2.0 pulls onnxruntime (80 MB), numpy, networkx, pymupdf4llm | 10/10 | 0.2 s (3.3 s cold) | Good text, but the licence and the size rule it out. |
| poppler `pdftotext` | GPL-2/3 | system binary (Homebrew) | 10/10 | 0.1–0.3 s | Not pip-installable. |

Every extractor interleaves footnotes into two-column body text and flattens math into Unicode fragments. Whatever page text is stored must therefore be exactly what Verify matches against. On the PDF path, numbers checked by the invented-number check will only match if the normalisation is shared. Equation numbers such as `(2)` do appear in PDF text, unlike in LaTeX.

## Suggested shape of the flattener (input to the build ticket)

1. Detect the format by magic bytes:
   - `1f8b` then `ustar` at offset 257 means tar.gz.
   - `1f8b` without `ustar` means a single gzipped `.tex`.
   - `%PDF` means PDF.
   - Extract the tar with `tarfile` `filter="data"`.
2. Pick the main file:
   - Use the `00README.json`/`.XXX` `toplevel` entry if present.
   - Otherwise take the `.tex` files with uncommented `\documentclass` and `\begin{document}`. If there are several, pick the largest and log the others as a parse warning.
3. Strip comments:
   - `%` to end of line, but not `\%`.
   - `comment` env.
   - `\iffalse … \fi` (count nesting).
   - Everything after `\end{document}`.
4. Inline `\input`/`\include` recursively:
   - Accept braced and brace-less forms. Use a word-boundary regex so `\includegraphics` is not matched.
   - Resolve relative to the root, then the current dir, adding `.tex` if missing.
   - Guard against cycles and depth.
   - Log missing files; do not fail.
   - Consider `\import`/`\subimport` and `\subfile` later.
5. Drop `thebibliography … \end{thebibliography}`, `\bibliography{}` and `\bibliographystyle{}`. Keep everything after them.
6. Keep macros, `\label`, `\ref` and `\cite` verbatim.

On the 4 papers, the hand-rolled prototype of these steps matched latexpand except for whitespace. Any failure falls back to the PDF path, as SPEC §13 already plans.

## Open trade-offs for ticket "Quote format: raw LaTeX or detexed prose?"

1. **What the model quotes is what it read.**
   - If `flattened.txt` is raw LaTeX, quotes will contain `~\cite{Duane1987HMC}`, `$10^6$`, `68\%`, `\emph{…}` and user macros (`$\Uone$`). These are very common in the seed papers.
   - SPEC §7.4's normalisation (`~`, `\,`, `\ `) is not enough. Either the model is told to quote raw text exactly, or a shared canonicaliser runs on both quote and source: it removes `\cite{…}`/`\ref{…}`, maps `\%`→`%`, unwraps `\emph`/`\textit`, and so on. **That canonicaliser becomes the matching contract** and needs Golden-set tests.
2. **Detexed source is lossy, and the loss is silent.**
   - pylatexenc drops unknown user macros, so "U(1) gauge theory" becomes "a  gauge group".
   - It turns math into ad-hoc Unicode (`ϕ^4`, `τ_int`) and drops `\label`s.
   - A detexed `flattened.txt` would need per-paper macro registration to be faithful, and the invented-number check would see `10^6` rather than `10^{6}`/`10^6`.
3. **`loc` needs the raw structure either way.**
   - Section titles and `\label` keys survive only in raw text. Custom heading macros (`\ssection`) must be recognised, or `loc` must accept label keys.
   - Equation *numbers* (`Eq. (3)`, `(A2)`) are not in the source and would have to be computed by counting numbered environments, which is fragile with revtex appendix numbering, `\nonumber` and `eqnarray`. Possible approach: cite `loc` by section title or `\label` key, not by number.
4. **Hybrid option.** The model reads and quotes raw text, Verify matches through the canonicaliser, and the UI shows a detexed rendering of the quote, for example pylatexenc with `math_mode='with-delimiters'`, or KaTeX for math. User macros will not render in KaTeX unless the preamble's `\newcommand`s are passed through.
5. **Tokens.** Raw is about 20–24% larger than detexed: 57.1k vs 46.6k, 26.8k vs 21.7k, 39.2k vs 32.1k and 37.8k vs 31.7k characters. That is a minor cost cut by prompt caching, but it is real for the 50/week ceiling.
6. **PDF-sourced Cards** will have quotes in extractor text, not LaTeX. Whatever is chosen, the canonicaliser must also cover NFKC, U+FFFE/U+00AD and de-hyphenation, so that both `source_type`s go through one matching path.

## Sources

- latexpand: <https://ctan.org/pkg/latexpand> (BSD-3, v1.7.2, "does not deal with \includeonly"); `latexpand --help`.
- arxiv_latex_cleaner: <https://github.com/google-research/arxiv-latex-cleaner> (Apache-2.0; removes comments, `\iffalse`, unused files; no merge); `arxiv_latex_cleaner --help`.
- pylatexenc: <https://pylatexenc.readthedocs.io/en/latest/latex2text/>, <https://pypi.org/project/pylatexenc/> (MIT).
- pandoc: <https://github.com/jgm/pandoc> (GPL-2.0-or-later), <https://pandoc.org/MANUAL.html>; `pypandoc_binary` <https://pypi.org/project/pypandoc-binary/>.
- arXiv: <https://info.arxiv.org/help/00README.html> (toplevel declaration, `\documentclass` heuristic), <https://info.arxiv.org/help/submit_tex.html> (root-relative paths, `.bbl` naming).
- pypdf <https://pypi.org/project/pypdf/> (BSD-3); pypdfium2 <https://pypi.org/project/pypdfium2/> (Apache-2.0/BSD-3); pdfminer.six <https://pypi.org/project/pdfminer.six/> (MIT); PyMuPDF <https://pymupdf.readthedocs.io/en/latest/about.html> (AGPL/commercial). Licences and dependencies are confirmed from installed `pip show` metadata.
- Hands-on: seed-paper sources and PDFs from `arxiv.org/src/<id>` and `arxiv.org/pdf/<id>`, kept only in the session scratchpad.
