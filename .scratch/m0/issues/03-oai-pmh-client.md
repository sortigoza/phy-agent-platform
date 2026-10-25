# OAI-PMH client: sickle or hand-rolled?

Type: research
Status: resolved
Blocked by: —

## Question

Should Watch use the `sickle` library or a hand-rolled `httpx` + `lxml` client for `oaipmh.arxiv.org/oai`? Judge each against:
- the shared rate limiter (≥ 3 s between requests, one connection, coordinated across processes through a lock file);
- resumption tokens that expire at UTC midnight;
- `arXivRaw` parsing, including the version history;
- `noRecordsMatch`, and error handling with backoff on 429 and 503;
- how easy it is to record real responses as test fixtures.

Also confirm the exact `responseDate` and datestamp semantics the high-water mark depends on. Check that `from` is inclusive, and how an empty day is reported. Use live requests at a polite rate.

## Answer

Write our own `httpx` + `lxml` client: about 150 lines, plus a 60-line arXivRaw parser. Don't use `sickle`.
- sickle 0.7.0 has had no release or commit since 2020-05-17.
- It hard-codes `requests.get`, so the shared rate limiter can't be injected.
- It only retries 503, and it crashes when `Retry-After` is an HTTP-date.
- It drops the arXivRaw version labels.

Tests replay real XML fixtures through `httpx.MockTransport`. vcrpy is a poor fit because real pages are 1–3.5 MB.

Facts confirmed live and against arXiv's server code:
- **`from` and `until`:** `from` is inclusive from 00:00:00 UTC, and `until` runs to 23:59:59 UTC. The datestamp is the UTC date of the last metadata change.
- **Errors return HTTP 200** with an `<error code=…>` element. `noRecordsMatch` means an empty window, not a failure.
- **`responseDate`:** format is `YYYY-MM-DDThh:mm:ssZ`.
- **Pages:** about 1300 records each, so a normal daily run is one page per set.
- **Resumption tokens:** the last page carries an empty token element, and a response that fits on one page has no token element at all.
- **CDN caching:** arXiv's CDN caches list responses for about 1 h (4 days for windows entirely in the past), and caches errors until UTC midnight. A cached `responseDate` is never later than the data it covers, so the high-water mark stays safe. Cache-busting query parameters are rejected.
- **Missing columns:** arXivRaw `<version><date>` is the submission time, not the announcement time. `<source_type>` is a sparse single-letter flag. The spec therefore records `first_seen_datestamp`, the datestamp of the harvest that first carried a version, instead of `announced_date`. Read detects `source_type` when it downloads.
- **Not tested live:** no real 429 or 503 was triggered, so the backoff behaviour rests on reading the code.

**Spec changes made:** SPEC §6 (`paper_versions` columns) and §7.1 (a CDN staleness note, and error handling for HTTP 200).

**Assets:**
- branch `research/oai-pmh-client` (commit `a64d315`, never merged);
- the findings at `.scratch/m0/research/oai-pmh-client.md` on that branch;
- fixtures in `.scratch/m0/research/fixtures/` on that branch, about 41 KB of metadata only. The slicing ticket should move them into `tests/fixtures/`.
