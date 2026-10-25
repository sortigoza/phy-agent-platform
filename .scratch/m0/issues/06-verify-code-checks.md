# Code checks in Verify

Type: grilling
Status: open
Blocked by: 01, 04

## Question

What exactly do the code checks in Verify do? Decide them against the prototype Card's real output:
- the normalisation rules for verbatim matching;
- what counts as a "number" in `key_results`, and how tolerant matching is (scientific notation, `\times10^{}`, units, error bars like `0.123(4)`);
- whether a partial-quote or ellipsis match is allowed;
- how locations are checked;
- the status and badge a Card gets when it fails each check.
