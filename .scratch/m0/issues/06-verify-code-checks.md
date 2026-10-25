# Code checks in Verify

Type: grilling
Status: open
Blocked by: 01, 04

## Question

What exactly do the code checks in Verify do? Decide them against the prototype Card's real output:
- what counts as a "number" in `key_results`, and how tolerant matching is (scientific notation, `\times10^{}`, units, error bars like `0.123(4)`);
- how `loc` is derived from the match position (heading detection, the enclosing environment's `\label`, page counting for PDF), and how `key_equations` and `key_figures` labels are checked;
- the status and badge a Card gets when it fails each check.

## Context

Already decided by [Quote format](01-quote-format.md): the canonicaliser rules, the quote shape (contiguous, 5–60 words, no ellipses) and that `loc` is computed rather than checked. What remains is number tolerance, the derivation details and the failure statuses.
