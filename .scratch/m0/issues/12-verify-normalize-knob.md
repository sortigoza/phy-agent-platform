# Keep, wire up or drop the `verify.normalize` knob?

Type: grilling
Status: open
Blocked by: —

## Question

QUICK_START §6 documents `verify.normalize` ("whitespace, quotes, dashes, LaTeX spacing": how quotes are normalised before verbatim matching), and `config.toml` / `VerifyConfig` accept it. Verify ignores it: slice 04 built `canonicalise(text, source_type)` as one fixed matching contract, as SPEC §7.4 and [Quote format](01-quote-format.md) decide ("one function … is the matching contract for both source types"). The knob and the contract disagree. Decide one of:

- **Drop it** (recommended when this was filed): remove the key from `src/phy/defaults/config.toml`, `VerifyConfig` and QUICK_START. Existing `$PHY_HOME/config.toml` files then fail validation (`extra="forbid"`), so `phy` needs to tell the Reader to delete the line.
- **Wire it up:** let `canonicalise` skip rule groups. Every combination then needs tests, a Golden eval result depends on a config value as well as on code and prompts, and the eval run must record it.
- **Keep it documented but inert:** not an option worth keeping; it misleads whoever tunes it.

## Context

- Found while building [Verify: quotes and locations](../../m0-build/issues/04-verify-quotes-and-loc.md) (commit `af71771`).
- The QUICK_START row's "Change it when: real quotes fail on formatting" is better served by adding a rule to `canonicalise` with its unit test, which applies to every Card and every Golden run alike.
- Re-evaluate once [Verify: numbers, labels and caps](../../m0-build/issues/05-verify-numbers-labels-caps.md) has landed and a week of real Cards shows whether any quotes fail on formatting.
