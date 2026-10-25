# Verify: numbers, labels and caps

Type: AFK
Status: open
Blocked by: 04

## Goal

Verify completes the M0 code checks: invented and ungrounded numbers, label warnings and list caps, with the Card's counts stored.

## Sources

SPEC §7.4 checks 2, 4, 5 and the paragraph after them, §6 `cards` columns; [Code checks in Verify](../../m0/issues/06-verify-code-checks.md).

## Acceptance criteria

- One number extractor runs on values, quotes and source: optional sign, decimals, `(d)` uncertainty, exponent in all three spellings; digits glued to identifiers are not numbers (`\phi^4`, `V^2`, `m_p`, `2D`) except `%` and `10x`/`10×`; words ignored.
- Equality by decimal value plus significant figures, sign ignored; `4.03(6)` and `4.03 \pm 0.06` both give `4.03` and `0.06`.
- Invented numbers: every number in any Fact's value and in `tldr` must appear in the canonical source; a miss makes the Fact `unsupported` and lands in `invented_numbers_json`.
- Ungrounded numbers: a number in a Fact's value missing from that Fact's own quotes makes a `supported` Fact `inferred` and is stored as `ungrounded_numbers`. Precedence `unsupported` > `inferred` > `supported`, with the model's `inferred: true`.
- Labels: missing `key_equations`/`key_figures` label, equation `latex` not a substring of its environment, figure label outside a `figure` environment → warnings only.
- Caps: over-cap lists (including > 2 quotes) trimmed to the first N with an `over_cap` warning carrying the dropped count; zero `key_results` warns.
- `unsupported_count` (inferred excluded), `inferred_count`, `invented_numbers_json`, `warnings_json` (`{kind, field, detail}`) stored; status stays `verified`.

## Tests first

- Extractor table test: at least 30 cases covering every SPEC example, both positive and negative.
- Equality: `1.2e-3` = `1.2\times10^{-3}` = `0.0012`; `1.20` ≠ `1.2`; `0.7` ≠ `70%`.
- Invented number in `tldr`; ungrounded number in a value; precedence with `inferred: true`.
- Each label warning; each cap trim; counts on a mixed Card.

## Lift from

`origin/prototype/card-schema-read-prompt:.scratch/m0/prototypes/card-read/verify.py` (number grounding).

## Not in this slice

The M1 model reviewer.
