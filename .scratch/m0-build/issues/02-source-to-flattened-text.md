# Source to flattened text

Type: AFK
Status: open
Blocked by: 01

## Goal

`phy read --paper 1904.12072 --dry-run` fetches the Paper's metadata and source through the shared arXiv rate limiter and writes `flattened.txt`, ready for the model.

## Sources

SPEC §5 arXiv access, §6 `papers`/`paper_versions`, §7.1 (arXivRaw parsing, OAI errors), §7.3 Fetching source / Flattening LaTeX / PDF fallback; [OAI-PMH client: sickle or hand-rolled?](../../m0/issues/03-oai-pmh-client.md); [LaTeX flattening and detex tooling](../../m0/issues/02-latex-flattening-tooling.md); [Quote format: raw LaTeX or detexed prose?](../../m0/issues/01-quote-format.md).

## Acceptance criteria

- `arxiv.py`: one `httpx` client behind the rate limiter (one request at a time, ≥ 3 s apart across processes via `arxiv.lock` holding the last request time; backoff sleeps inside the lock); retries with exponential backoff on 429, 503 and network errors, up to 3 attempts, then the Stage run fails.
- OAI-PMH errors returned as HTTP 200 `<error code=…>` are raised as typed errors; `noRecordsMatch` is an empty result.
- An `arXivRaw` record parser (shared with Watch in slice 08) yields title, authors, abstract, categories, license and the version history with submitted dates.
- `read --paper <id>` with an unknown Paper calls `GetRecord` (`metadataPrefix=arXivRaw`) and upserts `papers` and `paper_versions` exactly as Watch will. It takes the latest version, bypasses Filter and writes no `screenings` row.
- Source fetch from `arxiv.org/src/<id>v<n>` into `$PHY_HOME/papers/<id>v<n>/`; format detected from magic bytes (gzip then tar, single gzipped `.tex`, PDF); `source_type`, `local_path`, `sha256`, `fetched_at` recorded. A second run reuses the download.
- The flattener: main file from `00README` toplevel, else the uncommented `\documentclass` file; recursive `\input`/`\include` (braced and brace-less); strips `%` comments, `comment` environments, `\iffalse` blocks, text after `\end{document}`; drops the bibliography but keeps what follows it. Output is raw LaTeX, never detexed.
- PDF fallback with `pypdfium2`: soft hyphens stripped, hyphenated line breaks joined, NFKC, pages separated by `\f`.
- `--dry-run` stops after `flattened.txt` and prints its size and the token count from the free `count_tokens` endpoint. It takes `phy.lock`.
- Migration `002_papers` creates `papers` and `paper_versions`.

## Tests first

- Rate limiter: two processes issue requests ≥ 3 s apart (time faked); retry on 503 then success; 3 failures raise.
- The OAI fixtures from `research/oai-pmh-client` (`.scratch/m0/research/fixtures/`) move to `tests/fixtures/oai/`; the parser reads the hep-lat page; error and `noRecordsMatch` fixtures behave as above; add a recorded `GetRecord` response for 1904.12072 (metadata only).
- Magic-byte detection for each of the three formats (tiny synthetic archives built in the test).
- Flattener: one test per rule on synthetic `.tex` trees, including nested brace-less `\input`, `00README` precedence, appendix after `\bibliography`.
- PDF: a tiny PDF generated in the test round-trips with `\f` separators and joined hyphens.

## Lift from

`origin/prototype/card-schema-read-prompt:.scratch/m0/prototypes/card-read/flatten.py`; the research notes at `origin/research/latex-flattening:.scratch/m0/research/latex-flattening.md` and `origin/research/oai-pmh-client:.scratch/m0/research/oai-pmh-client.md`.

## Not in this slice

The model call (03), ListRecords and the high-water mark (08), key-figure image extraction (06).
