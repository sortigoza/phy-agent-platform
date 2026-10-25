# Golden set

Type: AFK
Status: open
Blocked by: 03

## Goal

`phy golden add <id> --split dev` freezes a Paper's source and drafts a Placeholder Reference card into a versioned manifest.

## Sources

SPEC §6 (`golden/`, `golden_sources/`), §10 Versioning / Splits / Provenance / Frozen inputs / Placeholders; QUICK_START §3 and the manifest table.

## Acceptance criteria

- `golden/manifest.yaml` model (Pydantic, `extra="forbid"`): `version` and per-Paper pinned version, sha256, `split` (`dev`, `held_out`), `status` (`placeholder`, `trusted`), `reason`, `expect_in_scope`, provenance (who corrected it, when).
- `golden add` copies the downloaded source (fetching it through slice 02 if needed) into `golden_sources/<id>v<n>/` with its `flattened.txt` and records the sha256; runs Read and Verify on it without touching `cards`; writes `golden/<id>/reference.json`; adds the entry as `placeholder` and bumps `version`. It refuses a duplicate, and refuses a fifth Paper while M0's cap of 4 Dev Placeholders holds.
- `--reason` defaults to `seed`; `--split held_out` is rejected in M0.
- A sha256 mismatch on any frozen source is reported by `phy golden check` (used by eval in 14).
- phy never commits; the command prints the `git` command the Reader may run.

## Tests first

- Manifest round-trip; unknown key rejected.
- `golden add` with replayed HTTP and the recorded Read response: files land, manifest bumps, `cards` untouched; duplicate refused; cap enforced.
- `golden check` detects a modified source.

## Lift from

Nothing.

## Not in this slice

Scoring (14), Trusted promotion workflow beyond the manifest field (manual per QUICK_START §8).
