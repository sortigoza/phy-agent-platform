# Quick Start

> **Status:** this describes the M0 target interface from [`docs/SPEC.md`](docs/SPEC.md). The code is not built yet. Commands marked *(M1)* or *(M2)* come later.

Terms such as Card, Flag, Candidate and Golden set are defined in [`GLOSSARY.md`](GLOSSARY.md).

## 1. One-time setup

```sh
# Prerequisites: macOS, uv (https://docs.astral.sh/uv/), Python 3.13
uv sync                                  # install dependencies from uv.lock

# Credentials: the SDK finds them itself
ant auth login                           # writes ~/.config/anthropic/, which launchd jobs can read
# (an exported ANTHROPIC_API_KEY also works interactively, but launchd never sees shell profiles)

uv run phy init                          # creates ~/.phy-agent-platform/ (seeded config, questions,
                                         # golden/, CHANGELOG.md; git init), the db, and checks auth
```

Everything the installation owns lives in `$PHY_HOME`, `~/.phy-agent-platform` by default (set `PHY_HOME` to move it). The repo holds only code and prompts. `$PHY_HOME` is a local git repo: commit your config, questions, Golden and changelog edits there; phy never commits for you. Paths below such as `config.toml` and `golden/` are relative to `$PHY_HOME`.

Before the first run, set a **monthly spend cap** in the Anthropic Console. That cap is the hard ceiling. The pipeline's own `budget.weekly_usd` is the soft one.

## 2. Tell it what you care about

Edit `questions.yaml`. It is the only place that decides relevance.

```yaml
questions:
  - id: Q1
    title: Generative sampling for lattice field theory
    description: >
      How well do normalizing flows, diffusion models and related samplers beat
      critical slowing down and topological freezing? Scaling with volume and gauge symmetry?
    keywords: [normalizing flow, diffusion model, generative, sampler, topological freezing]
    negative_keywords: []
physics_terms: [lattice, gauge, Hamiltonian, spin, fermion, QCD, many-body]   # for cs.LG / stat.ML
negative_keywords: [quantum hardware, superconducting qubit fabrication]   # code pre-filter only
scope_notes:                       # prose rules the Filter model applies; keywords never reach the model
  - '"Renormalization" or "lattice" used only in a machine-learning sense, with no physical system.'
  - Quantum-computing hardware, devices or benchmarks of quantum processors.
  - Machine-learning methods or benchmarks with no physics application.
```

## 3. First end-to-end run (a smoke test on one paper you know)

```sh
uv run phy golden add 1904.12072 --split dev   # freeze source, draft a Placeholder reference card
uv run phy read --paper 1904.12072             # card one paper, bypassing Watch/Filter/quota
uv run phy verify
uv run phy ui                                  # open http://127.0.0.1:8000/review
```

Check that the Card is right, the quotes expand, and the unsupported fields are shaded. Then add up to 3 more seed Papers with `phy golden add` (2003.06413, 1606.02318, 1605.01735).

## 4. First real harvest

```sh
uv run phy daily                     # Watch (backfills watch.backfill_days) → Filter → Read → Verify
uv run phy watch                     # or Watch alone: harvest every set since the mark
uv run phy status                    # high-water mark, funnel counts, week's spend, last failures
```

The first harvest pulls about 14 days of metadata at 1 request every 3 s. Expect it to take minutes, not seconds.

## 5. Schedule it

The schedule runs a **Release**, a tagged version, from its own checkout at `$PHY_HOME/app`, so work in progress in your clone never runs at 06:00. Cut one first:

```sh
git tag -a v0.1.0 -m "First release"  # on main; phy never tags
uv run phy schedule install          # checks out the newest Release in $PHY_HOME/app, writes + loads ~/Library/LaunchAgents/phy.daily.plist
uv run phy schedule status
```

When you tag a newer Release, the UI top bar shows "update available", and so does `phy status`. Install it when you choose:

```sh
uv run phy schedule update           # refuses a downgrade; does nothing while a run holds the lock
```

The job runs at 06:00 and at login.
- **Asleep at 06:00:** it runs when the Mac wakes.
- **Shut down:** it runs at the next login.
- **Missed days:** the high-water mark catches them up, so nothing is lost.

Logs go to `$PHY_HOME/logs/phy-YYYY-MM-DD.jsonl` (stderr shows the same events in readable form). Crashes before logging starts land in `$PHY_HOME/logs/launchd.err`.

## 6. Your weekly routine

| When | Do | Where |
| --- | --- | --- |
| Weekday mornings, ~25 min | Review about 6 Cards: relevance, Flags, deep read | `/review` |
| Monday, 10 min | Look at the red tiles only, and follow each tile's action | `/monitor` |
| Friday, 10 min | Spot-check 2 random Cards against their papers | `/review?random=2` |
| Weekend | Deep read 1–2 papers marked deep_read=yes | `/review?deep_read=1` |
| Monthly, 2 h | Meta-work (section 8), add 2 Golden Papers, promote Placeholders | CLI and editor |

**Never edit a Card.** Flag it. A Flag is input for fixing the prompt, not the Card.

## 7. Knobs

All knobs live in `config.toml` unless noted. Change one at a time, and check the Instrument it affects.

### Watch

| Key | Default | What it does | Change it when |
| --- | --- | --- | --- |
| `watch.sets` | the 8 sets in SPEC §4 | Which OAI-PMH sets are harvested | You add or remove a subfield |
| `watch.prefilter` | per set: `none`, `keywords` or `keywords+physics` | Whether the keyword pre-filter applies to that set | Candidates/week is out of range, or the missed-papers log shows recall gaps |
| `watch.backfill_days` | `14` | How far back the first run, or a run after `phy watch --reset`, starts | You want a longer initial history |
| `arxiv.min_interval_s` | `3.0` | Rate limit between arXiv requests | Never lower it below 3 (arXiv ToU) |
| `arxiv.max_retries` | `3` | Backoff attempts on 429, 503 or network errors | Transient failures show up in `/monitor` |

### Filter

| Key | Default | What it does | Change it when |
| --- | --- | --- | --- |
| `filter.model` | `claude-haiku-5-5` | The scoring model | Filter precision is low and prompt fixes didn't help |
| `filter.effort` | `low` | How much thinking the model does per Candidate | Same as above (try `medium`) |
| `filter.threshold` | `0.5` | Minimum best_score to be Screened in | Precision is low (raise it) or recall is low (lower it) |
| `filter.prompt_version` | `v1` | Which `prompts/filter/<v>.md` is used | After a Meta-work cycle |
| `questions.yaml` | 4 questions | Questions, keywords, negative keywords and scope notes | Funnel shape, precision, or your interests change |

### Read

| Key | Default | What it does | Change it when |
| --- | --- | --- | --- |
| `read.daily_quota` | `8` | Cards per day; unused quota carries over within the ISO week | Your review backlog grows (lower it) or stays empty (raise it) |
| `read.always_threshold` | `0.9` | A best_score this high is always Carded | Too many marginal papers jump the queue |
| `read.weekly_ceiling` | `50` | Hard cap on Cards per week | Your attention budget changes |
| `read.model` | `claude-sonnet-5-5` | The Card-writing model | Field accuracy plateaus (try `claude-opus-5-5` and re-run the Golden set) |
| `read.effort` | `medium` | How much thinking the model does per Card | The unsupported-field rate is high (raise it) or cost is high (lower it) |
| `read.prompt_version` | `v1` | Which `prompts/read/<v>.md` is used | After a Meta-work cycle |
| `read.recard_stale` | `relevant_only` | Re-card new versions of Papers you rated yes or partly | You want every new version re-carded (`all`) or none (`never`) |
| `read.use_batch` *(M1)* | `false` | Send Read calls through the Batch API (50% off, results usually within 1 h) | Cost matters more than same-morning Cards |

### Verify, budget and alerts

| Key | Default | What it does | Change it when |
| --- | --- | --- | --- |
| `verify.normalize` | whitespace, quotes, dashes, LaTeX spacing | How quotes are normalised before verbatim matching | Real quotes fail on formatting; check the run viewer first |
| `budget.weekly_usd` | `20` | Read stops selecting for the rest of the week at this spend | Deliberately, never just to silence the tile |
| `prices.<model>` | 2026-10 list prices | Used for every cost figure | Anthropic changes prices |
| `alerts.candidates_range` | `[100, 400]` | Bounds of the Candidates/week tile | Week 1 shows the real volume |
| `alerts.unsupported_rate` | `0.10` | Red line for unsupported fields | Rarely |
| `alerts.review_minutes` | `5` | Red line for median review time | Rarely; trim the Card instead |
| `alerts.minutes_per_relevant` | `8` | Red line for your review minutes per relevant Card | Rarely; check whether review time or precision moved |
| `alerts.wasted_minutes` | `40` | Red line for weekly minutes spent reviewing Cards you rated no | Precision targets change |
| `roi.baseline_minutes` | `15` | Minutes a paper would take you without the platform (a skim, not a full read); feeds the time multiplier | You time a few skims and get a different number |
| `ui.port` | `8000` | Port the UI binds to on `127.0.0.1` | The port is taken |

### Golden set

Edit `golden/manifest.yaml`. Any change bumps `version`.

| Field | Values | Meaning |
| --- | --- | --- |
| `split` | `dev`, `held_out` | Dev you may inspect. Held-out is scored only to accept a change. |
| `status` | `placeholder`, `trusted` | Only Trusted Papers produce accuracy scores |
| `reason` | `seed`, `review_mistake`, `out_of_scope_probe`, `awkward_source` | Why the Paper is in the set |
| `expect_in_scope` | `true`, `false` | Expected Filter decision |

## 8. Meta-work: changing the system safely

```sh
cp prompts/read/v1.md prompts/read/v2.md       # never edit a used version in place
$EDITOR prompts/read/v2.md                     # address the Flags / red tile you saw
uv run phy eval --prompt read=v2               # Golden set: grounding, invented numbers, filter, diff vs the accepted run
# open the printed /eval/<id> link and review the Material changes
# accept only if nothing regressed:
#   set read.prompt_version = "v2" in config.toml
uv run phy eval accept <id>                    # refuses if config doesn't match the run, or on a hard fail
#   then add a line to CHANGELOG.md and commit
```

Useful inputs for Meta-work:
- `uv run phy flags --since 30d`: Flags grouped by field and kind.
- `/monitor`: the red tiles, each linking to the runs behind it.
- `/runs/<id>`: the exact request and response.

To promote a Placeholder to Trusted:
1. Correct `golden/<id>/reference.json` field by field.
2. Set `status: trusted`.
3. Bump the manifest `version`.

## 9. When something looks wrong

| Symptom | First thing to check |
| --- | --- |
| "Days since mark advanced" is red | `phy schedule status`, `$PHY_HOME/logs/`, then the last Watch run in `/runs` |
| Zero papers harvested on a weekday | arXiv holiday? Otherwise the Watch run log (OAI-PMH errors) |
| A Card says unsupported but the quote looks right | Run viewer: compare the quote with `flattened.txt`; probably a normalisation knob |
| Invented-number badge | The run viewer. This is never acceptable, so Flag it and add the Paper to the Golden set |
| Garbled Card from an odd submission | `$PHY_HOME/papers/<id>v<n>/flattened.txt`. A flattener bug: add the Paper as an `awkward_source` Golden Paper |
| Need to re-harvest a window | `uv run phy watch --since 2026-10-01` (idempotent) |
| Need to redo one Stage | `uv run phy <stage> [--paper ID] [--force]`. Every Stage is rerunnable alone |
