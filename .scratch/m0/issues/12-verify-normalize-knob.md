# Keep, wire up or drop the `verify.normalize` knob?

Type: grilling
Status: resolved
Blocked by: —
Assignee: Saul

## Question

QUICK_START §6 documents `verify.normalize` ("whitespace, quotes, dashes, LaTeX spacing": how quotes are normalised before verbatim matching), and `config.toml` / `VerifyConfig` accept it. Verify ignores it: slice 04 built `canonicalise(text, source_type)` as one fixed matching contract, as SPEC §7.4 and [Quote format](01-quote-format.md) decide ("one function … is the matching contract for both source types"). The knob and the contract disagree. Decide one of:

- **Drop it** (recommended when this was filed): remove the key from `src/phy/defaults/config.toml`, `VerifyConfig` and QUICK_START. Existing `$PHY_HOME/config.toml` files then fail validation (`extra="forbid"`), so `phy` needs to tell the Reader to delete the line.
- **Wire it up:** let `canonicalise` skip rule groups. Every combination then needs tests, a Golden eval result depends on a config value as well as on code and prompts, and the eval run must record it.
- **Keep it documented but inert:** not an option worth keeping; it misleads whoever tunes it.

## Context

- Found while building [Verify: quotes and locations](../../m0-build/issues/04-verify-quotes-and-loc.md) (commit `af71771`).
- The QUICK_START row's "Change it when: real quotes fail on formatting" is better served by adding a rule to `canonicalise` with its unit test, which applies to every Card and every Golden run alike.
- Re-evaluate once [Verify: numbers, labels and caps](../../m0-build/issues/05-verify-numbers-labels-caps.md) has landed and a week of real Cards shows whether any quotes fail on formatting.
- **2026-10-26:** the trigger above has fired. The first scheduled runs produced 97 real Verified Cards, so count which quotes failed and whether any failed only on formatting (`cards.card_json` Support plus the flattened text in `$PHY_HOME`) before deciding.

## Resolution

**Drop the knob. Fix the formatting failures with specific `canonicalise` rules. Let long equations pass the length rule. Re-verify every Card after the fix Release.**

Evidence (2026-10-26, all 97 Cards; the survey scripts and output are in the session scratchpad and aren't committed, since they quote arXiv text): **48 of 1,618 quotes fail (3.0%)**.
- **27 are under 5 words but found verbatim,** almost all equations quoted as `key_results` evidence. 26 of them match exactly once.
- **About 11 are formatting only:**
  - first-letter case: 5
  - a dropped `align` `&`: 2
  - spacing inside math: 2
  - `\mathcal M` versus `\mathcal{M}`: 1
  - a dropped `\rm`: 1
  - a stray trailing `}`: 1
- **About 10 are real misquotes,** with the model changing words. Verify is right to fail these.
- **Failure rate by field:** `key_results` 29/553, `assumptions` 11/308, everything else ≤ 3.

1. **Drop `verify.normalize`** from `src/phy/defaults/config.toml`, `VerifyConfig` and QUICK_START. Loading a config that still has it fails with "`verify.normalize` was removed; delete it from config.toml". The Reader deletes the line from `$PHY_HOME/config.toml` at the same time as `phy schedule update` to the fix Release, since `v0.1.0` requires the key. Build ticket 17's checklist says so.
2. **New `canonicalise` rules,** each with a unit test from the failure it fixes:
   - LaTeX `&` alignment marks are dropped (`\&` is kept);
   - `\!` is dropped;
   - `\cmd{X}` with a one-character argument equals `\cmd X`;
   - the old font switches `\rm`, `\bf`, `\it`, `\sf`, `\tt` and `\em` are dropped;
   - the quote's first character matches without regard to case;
   - an unbalanced trailing `}` in a quote is stripped.

   That recovers about 9 of the 11. There's no math-whitespace rule, because it would need math-mode tracking for 2 quotes.
3. **The length rule becomes: at least 5 words *or* at least 30 non-space canonical characters,** with the 60-word maximum unchanged. That recovers 20 of the 27. Genuinely short quotes ("Consider state") still fail. This amends [Quote format](01-quote-format.md)'s 5–60-word rule; SPEC §7.4 changes.
4. **Re-verify every Card** with `phy verify --force` as a rollout step of the fix slice. It's free, and reviewed and Stale Cards keep their status.
