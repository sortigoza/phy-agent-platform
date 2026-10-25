# Watch

Type: AFK
Status: done
Blocked by: 02

## Goal

`phy watch` harvests every configured set since the high-water mark, upserts Papers and versions, advances the mark safely and marks Cards Stale.

## Sources

SPEC §4 sets, §6 `papers`/`paper_versions`/`state`, §7.1; QUICK_START `watch.backfill_days` and `phy watch --since`; [OAI-PMH client: sickle or hand-rolled?](../../m0/issues/03-oai-pmh-client.md).

## Acceptance criteria

- For each set in config: `ListRecords` with `metadataPrefix=arXivRaw`, `from=<hwm>`, no `until`, following resumption tokens to the end within the run; tokens never stored.
- Upserts on `arxiv_id` and (`arxiv_id`, `version`); `sets` accumulates across sets (dedup by id); `first_seen_datestamp` set once per version. New Paper, new version and metadata-only change are told apart; metadata-only creates no work.
- The mark moves to the first page's `responseDate` only after every set completed; `watch.last_success_at` recorded; with no mark, `from` is today minus `watch.backfill_days`. `--reset` clears the mark; `--since DATE` harvests a window without moving the mark backwards.
- A new version of a Paper with a Card makes that Card `stale`.
- One `runs` row per Watch run; INFO counts per set; takes `phy.lock`.

## Tests first

- Using `tests/fixtures/oai/`: single page; two pages via resumption token ending in an empty token; `noRecordsMatch`; `badResumptionToken` fails the run and leaves the mark.
- Mark only advances when all sets succeed (second set fails → unchanged).
- Three upsert cases from hand-built arXivRaw records; Card becomes `stale` on a new version.
- Re-running the same window is idempotent (row counts unchanged).

## Lift from

The parser and client from slice 02; `origin/research/oai-pmh-client:.scratch/m0/research/oai-pmh-client.md`.

## Not in this slice

Re-card selection of Stale Cards (10).
