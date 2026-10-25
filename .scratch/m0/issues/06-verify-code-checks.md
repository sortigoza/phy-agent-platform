# Code checks in Verify

Type: grilling
Status: resolved
Blocked by: 01, 04
Assignee: Saul

## Question

What exactly do the code checks in Verify do? Decide them against the prototype Card's real output:
- what counts as a "number" in `key_results`, and how tolerant matching is (scientific notation, `\times10^{}`, units, error bars like `0.123(4)`);
- how `loc` is derived from the match position (heading detection, the enclosing environment's `\label`, page counting for PDF), and how `key_equations` and `key_figures` labels are checked;
- the status and badge a Card gets when it fails each check.

## Context

Already decided by [Quote format](01-quote-format.md): the canonicaliser rules, the quote shape (contiguous, 5–60 words, no ellipses) and that `loc` is computed rather than checked. What remains is number tolerance, the derivation details and the failure statuses.

From [Card schema v1 and Read prompt v1](04-card-schema-and-read-prompt-prototype.md), also decide:
- the **per-field number check**: each number in a Fact's value must appear in that Fact's own quotes. Its tolerance, and the status it gives (`inferred`, `unsupported`, or a badge);
- how **over-cap lists** are trimmed (keep the first N) and where the warning is shown;
- the **raw ↔ canonical offset mapping** `loc` needs. The prototype's rough locator put one quote in "front matter", because `~\ref{…}` disappears under canonicalisation.

The prototype Card to decide against is `out/card.json` on branch `prototype/card-schema-read-prompt`. Its rough checks are in `verify.py` there.


## Answer

Decided against the prototype Card's real output. A rough per-field check on it flagged `system` (`6.975`, `5.113` are in a table, not its quote), `baselines` (`70`), `method` and `assumptions[2]`. It also exposed a false pass: the substring `4` in `\phi^4` matched the value's `m_p L ≈ 4`.

**What counts as a number.** A token with an optional sign, digits with an optional decimal part, an optional `(d)` uncertainty and an optional exponent (`e-3`, `\times10^{-3}`, `×10⁻³`).
- Digits glued to an identifier are not numbers: after a letter, `_`, `^` or `\` (`\phi^4`, `V^2`, `m_p`), or before a letter (`2D`, `3rd`). The exceptions are `%` and an `x`/`×` multiplier (`10x`).
- Numbers written as words ("one to two") are ignored.
- One extractor runs on the value, the quotes and the source. Comparison is set membership of parsed numbers, never substring matching.

**Tolerance.** Two numbers are equal when both their decimal value and their significant figures match: `1.2e-3` = `1.2\times10^{-3}` = `0.0012`, but `1.20` ≠ `1.2`.
- The sign is ignored, because dashes are ambiguous (`6-14`, `m^2=-4`).
- Error bars split into two numbers: `4.03(6)` and `4.03 \pm 0.06` both give `4.03` and `0.06`.
- Units are not checked. `70%` matches `70` but not `0.7`: a conversion counts as inferred per field, and as invented against the whole source.

**Invented-number check (whole source).** Covers every Fact's value plus the `tldr`, not only `key_results`. Opinion fields and equation `meaning`s are excluded.
- A miss makes that field `unsupported`, so it counts in `unsupported_count`.
- The miss is added to the Card's `invented_numbers` list, which drives the red badge.
- The `tldr` has no Support, so a miss there only adds to `invented_numbers`.

**Per-field number check.** A number that is in the source but not in the field's own quotes downgrades `supported` to `inferred`. The missing numbers are stored on the Fact as `ungrounded_numbers`, so the UI can highlight them. They don't count as unsupported.

**Quotes: all must pass.** Every Evidence quote on a Fact must be found and meet the shape rules, or the Fact is `unsupported`. The prototype's "any quote found" was wrong. A Fact with zero Evidence is `unsupported`, a defensive case, since the schema enforces `min_length=1`.

**Support precedence:** `unsupported` > `inferred` > `supported`. A failed quote or an invented number gives `unsupported`. Otherwise the model's `inferred: true` or any ungrounded number gives `inferred`. Otherwise the field is `supported`.

**Raw ↔ canonical offset mapping.** `canonicalise` is built as a single pass that records the raw offset of every canonical character.
- `canonicalise()` returns the string, and `canonicalise_mapped()` returns the string plus the offset array.
- `loc` maps the first canonical match back exactly, which fixes the prototype's "front matter" bug from `~\ref{…}`.
- Matching and locating share one code path.

**`loc` format.**
- The innermost heading, kept as raw LaTeX and rendered with KaTeX: `Sec. "…"`, or `App. "…"` after `\appendix`.
- `Abstract` inside `\begin{abstract}`, and `front matter` before the first heading.
- `· <label>` when the match is inside `equation`, `align`, `gather`, `multline`, `eqnarray`, `figure` or `table` (starred variants included).
- On the PDF path, `p. N`, counted from `\f`.

**`key_equations` and `key_figures`.** These checks give warnings only and never change Support, because these entries aren't Facts.
- A label missing from the source gives a warning, and the entry stays visible with a chip.
- For `key_equations`, the canonical `latex` must be a substring of the canonical body of its label's environment.
- For `key_figures`, the label must sit in a `figure` environment.

**Card status and badges.** There is no new status: after Verify the status is always `verified`, meaning Verify ran. A Card is never hidden by its failures, which are stored as data:
- `invented_numbers` (a list) drives the red badge;
- `warnings` (a list of `{kind, field, detail}`, with kinds `over_cap`, `no_key_results`, `unknown_label`, `equation_mismatch` and `figure_label_not_figure`) drives grey chips on their sections;
- `unsupported_count` excludes inferred fields, and `inferred_count` is also stored for the Monitoring page.

**List caps.** An over-cap list, including more than 2 Evidence quotes, keeps its first N, and an `over_cap` warning records the dropped count. The dropped items aren't kept on the Card, because the raw response is already in the run trace. Zero `key_results` gives a warning.

SPEC §7.4 and the `cards` table in §6 are updated to match.
