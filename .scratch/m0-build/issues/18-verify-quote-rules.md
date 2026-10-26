# Verify: quote rules from the first real Cards

Type: AFK
Status: open
Blocked by: 20

## Goal

Quotes that failed only on formatting, or only because they're short equations, now pass. Unknown question ids are dropped. The inert `verify.normalize` knob is gone.

## Sources

Map ticket [Keep, wire up or drop the verify.normalize knob](../../m0/issues/12-verify-normalize-knob.md); [Read failure bookkeeping](../../m0/issues/18-read-failure-bookkeeping.md), item 4; SPEC §7.4; QUICK_START §6.

## Acceptance criteria

- `verify.normalize` is removed from `src/phy/defaults/config.toml`, `VerifyConfig` and QUICK_START. A config that still has it fails to load with "`verify.normalize` was removed; delete it from config.toml", not the generic `extra="forbid"` error.
- `canonicalise` gains six rules, in both `canonicalise` and `canonicalise_mapped` (offsets stay exact):
  - LaTeX `&` alignment marks are dropped, while `\&` is kept;
  - `\!` is dropped;
  - `\cmd{X}` with a one-character argument canonicalises like `\cmd X`;
  - the old font switches `\rm`, `\bf`, `\it`, `\sf`, `\tt` and `\em` are dropped;
  - a quote's first character matches without regard to case;
  - an unbalanced trailing `}` in a quote is stripped.
- The length rule is at least 5 words **or** at least 30 non-space canonical characters; the maximum stays 60 words.
- Verify drops a `questions[]` entry whose id isn't in `questions.yaml` and adds a `CardWarning` (new kind `unknown_question`).
- SPEC §7.4 and the Quote format wording (5–60 words) are updated.

## Tests first

- One synthetic `.tex` snippet per rule, modelled on the failure it fixes (see the map ticket's evidence): the quote fails before the rule and is found after, with `loc` unchanged.
- Each rule has a negative test: a real word change still fails.
- Length: a 1-word equation of 30+ characters passes; "Consider state" (13 characters) fails.
- Config: the old key gives the named error.
- An unknown question id is dropped with a warning.

## Lift from

Nothing.

## Not in this slice

Ignoring spacing inside math (2 quotes, needs math-mode tracking). Re-verifying existing Cards is a rollout step in [M0 burn-in](17-burn-in.md), not code.
