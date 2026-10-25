# Physics Agent Platform

A personal platform where agents do the bulk reading of physics research and the Reader spends attention only where it matters. v1 runs one Workload: paper reading.

## Language

### Platform

**Workload**:
A complete end-to-end job the platform performs for the Reader, from source to reviewed output. v1 has exactly one: paper reading. "Platform" means the shape every Workload shares (Stages, Instruments, Golden set, Meta-work), not a generic layer.
_Avoid_: plugin, pipeline (when meaning the whole Workload)

**Reader**:
The single human the platform serves. Reviews Cards, raises Flags, and does Meta-work.
_Avoid_: user, operator

**Stage**:
One step of a Workload with one kind of input and one kind of output, rerunnable on its own. Paper reading has Watch, Filter, Read and Verify (later Synthesize and Digest).

**Instrument**:
A measured signal about the Workload (is it running, is it right, is it useful, is it affordable) with a threshold and a named action when it fires. An Instrument with no action is deleted.
_Avoid_: metric (when meaning a thresholded signal with an action)

**Meta-work**:
Changing prompts, parsers, schemas or config in response to Flags and Instruments, accepted only if the Golden set does not regress, plus crafting the Golden set itself. Fixing the system, not the output.

### Papers and the funnel

**Paper**:
One arXiv work, identified by its arXiv ID regardless of version.
_Avoid_: article, preprint

**Paper version**:
One numbered release of a Paper (v1, v2, ...). A Card is always made from, and its Evidence checked against, one specific Paper version.

**Candidate**:
A Paper that passed the pre-filter and goes on to be scored against the research questions.

**Screened in**:
A Candidate whose best score across the research questions reaches the relevance threshold.

**Carded**:
A Screened-in Paper selected for Read within the reading quota, and so given a Card.

**Reading level**:
How deeply a Paper has been absorbed: **L0 Screened** (agents scored it, the Reader spent no time), **L1 Carded** (the Reader reviewed its Card), or **L2 Deep read** (the Reader read it in full, with the Card as a guide).

### Cards

**Card**:
The structured, evidence-backed summary of one Paper version, built to be reviewed in about 4 minutes. The product of the paper-reading Workload.
_Avoid_: summary, note

**Card field**:
One named part of a Card (system, method, key result, ...). A factual Card field carries a value, its Evidence, and its Support.

**Evidence**:
A passage quoted verbatim from the Paper version's source text, backing a Card field's value. Its location (section and label, or page) is where the quote was found in the source, never the agent's claim about where it is.

**Key figure**:
A figure of the Paper the agent judges worth seeing, chosen from its caption and shown on the Card.

**Support**:
Whether a Card field's Evidence backs its value: **supported**, **unsupported** (no verbatim quote, or the quote does not back the value), or **inferred**. Unsupported fields are shown, never hidden.

**Opinion field**:
A Card field holding the agent's own judgement (flagged limitations, deep-read recommendation), always labelled as such and never mixed with the Paper's own claims.

**Stale**:
Describes a Card made from an older Paper version than the latest known. A Stale Card is re-carded only if its Review rated it relevant.

### The Reader's loop

**Review**:
The Reader's single pass over one Card: a relevance rating (yes, partly, no), any Flags, a deep-read choice, and the time spent.

**Flag**:
The Reader's mark that a Card field is wrong, of one kind: **wrong value**, **quote doesn't support**, **missing**, or **should be opinion**. A Flag is never fixed on the Card by hand; it is input to Meta-work.

### Evaluation

**Golden set**:
A versioned collection of Papers with Reference cards, used as the regression suite for reading. A change is accepted only if the Golden set does not regress.

**Reference card**:
The Card for a Golden set Paper against which generated Cards are scored.

**Placeholder** / **Trusted**:
The status of a Golden set Paper. A Placeholder's Reference card is an uncorrected draft: it can prove grounding, absence of invented numbers, the Filter decision and run-to-run change, but not accuracy. A Trusted Reference card has been corrected by the Reader field by field, and only Trusted Papers produce accuracy scores.

**Dev** / **Held-out**:
The two splits of the Golden set. Dev Papers may be inspected and iterated on freely during Meta-work; Held-out Papers are scored only to accept a change, and their per-field failures stay hidden so they never become tuning data.
_Avoid_: train / test
