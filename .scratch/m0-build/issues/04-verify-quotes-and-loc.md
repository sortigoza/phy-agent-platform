# Verify: quotes and locations

Type: AFK
Status: open
Blocked by: 03

## Goal

`phy verify` checks every quote on every draft Card against `flattened.txt`, sets Support from it, and derives each quote's `loc` and `match_count`.

## Sources

SPEC §7.4 checks 1 and 3, §8 rules; [Quote format: raw LaTeX or detexed prose?](../../m0/issues/01-quote-format.md); [Code checks in Verify](../../m0/issues/06-verify-code-checks.md).

## Acceptance criteria

- `canonicalise(text, source_type)` and `canonicalise_mapped()` (text plus raw-offset array) in one single pass, exactly the SPEC §7.4 rules for LaTeX and the PDF rules.
- A quote is found when canonical(quote) is a substring of canonical(source). Shape rules: one contiguous span of 5–60 words, no ellipsis, not crossing a paragraph or section boundary.
- Every quote on a Fact must be found and well-shaped, else the Fact is `unsupported`; a Fact with no Evidence is `unsupported`.
- `loc` from the first match: innermost heading as `Sec. "…"` / `App. "…"` (after `\appendix`), starred and preamble `section`-like macros; `Abstract`; `front matter`; `· <label>` inside the listed environments; `p. N` on the PDF path. `match_count` stored.
- `phy verify` processes every `draft` Card (catch-up), writes `card_json` as a `Card`, sets status `verified`, records a `runs` row, takes `phy.lock`; `--paper` and `--force` re-verify one.

## Tests first

- One unit test per canonicalisation rule from a hand-written seed-like snippet (cite with `~`, `\%`, `\emph`, dashes, `\,`, whitespace).
- `canonicalise_mapped()` offsets map every canonical char back to the right raw char.
- Shape rules: 4 words, 61 words, `...`, a quote crossing a blank line, crossing `\section`.
- `loc` cases: section, subsection inside appendix, abstract, front matter, equation label, figure label, `\ssection` macro, PDF page.
- End to end: the recorded 1904.12072 draft against a synthetic flattened text containing its quotes gives the expected Support.

## Lift from

`origin/prototype/card-schema-read-prompt:.scratch/m0/prototypes/card-read/verify.py`.

## Not in this slice

Numbers, labels and list caps (05).
