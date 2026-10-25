# OAI-PMH client: sickle or hand-rolled? (research for issue 03)

Researched 2026-10-25. Live requests went to `https://oaipmh.arxiv.org/oai`: 15 requests, at least 3 s apart, with a UA string that includes a contact address.

## Recommendation

**Write our own client with `httpx` and `lxml`.** It is about 150 lines, plus about 60 lines for the arXivRaw parser. Sickle does not fit our needs well:

- It hard-codes `requests.get`, so we cannot inject a session or the shared limiter without subclassing.
- Its retry handling is broken for our case. It ignores `Retry-After` on 429, and it crashes when `Retry-After` is an HTTP-date.
- Its metadata dict drops the `version="vN"` labels that Watch needs.

Once we work around all three, sickle only saves us about 40 lines: the resumption loop and the mapping from error codes to exceptions. In exchange we would take on a dependency on `requests` and a project with no release since 2020.

**Testing:** put real XML in fixture files and serve them with `httpx.MockTransport`, which ships with httpx, or with `respx`. Do not use vcrpy cassettes (see section 5).

**Spec impact (§7.1). Two findings need a decision before Watch is built:**

1. **The CDN caches responses (section 3.6).** A cached response carries the `responseDate` of the moment it was first rendered. That date is older than the real request time, so using it for the high-water mark is still safe: it can only move the mark less far, never past real data. **The spec rule holds**, but add a note that `responseDate` can be up to 1 h stale. Error responses, including `noRecordsMatch`, are cached until the next UTC midnight.
2. **`announced_date` is not in arXivRaw (section 3.5).** The `<version><date>` element holds the *submission* timestamp. `<source_type>` is a sparse flag (`D`, `A`, `I`), not latex/pdf. The `paper_versions.announced_date` and `source_type` columns in spec §6 therefore need another source: Read can detect the source type at download time. Alternatively, Watch can record the header `datestamp` that first carried each new version.

## 1. Comparison

| Criterion | sickle 0.7.0 | httpx + lxml (own) |
| --- | --- | --- |
| Maintenance | Last release 0.7.0 on 2020-05-17; last commit on the same day; 14 open issues [1][2] | httpx 0.28.1, lxml 6.1.3 (2026-09); both active |
| Python 3.11+ | Works on 3.13.14: I ran it offline against a saved response. Still has a py2 `_compat` shim and an undeclared `requires_python` | Yes |
| HTTP stack | Module-level `requests.get/post`, so no session, no connection reuse and no transport injection. Our only hook is overriding the private `_request` [3] | Same `httpx.Client` as `/src/` downloads, so one limiter wraps everything |
| Shared rate limiter (3 s, one connection, lock file) | Only by subclassing and overriding `_request`. Retries call `_request` again, so they would pass through the limiter | Built into the single `get()` call |
| 429 / 503 / network errors | Retries only the codes in `retry_status_codes` (default `[503]`). Honors `Retry-After` **only on 503**; every other code gets `default_retry_after=60` s. `int(Retry-After)` catches only `TypeError`, so an HTTP-date value raises `ValueError` and crashes. Network errors are not retried. `max_retries` defaults to 0 [3] | About 20 lines: backoff on 429, 503 and `httpx.TransportError`, with Retry-After in either seconds or HTTP-date form, up to 3 attempts (spec §5) |
| Resumption tokens | Followed automatically. The first request fires inside `ListRecords()` itself. `responseDate` is reachable only through `iterator.oai_response.xml` [4] | An explicit loop. We control per-page logging and capturing `responseDate` from the first page |
| `noRecordsMatch` | Raised as `NoRecordsMatch` from the `ListRecords()` constructor [4] | Checked explicitly: it means an empty window and is not an error |
| arXivRaw parsing | `Record.metadata` flattens all descendants by tag name. Verified: `{'version': [None, None], 'date': [...], 'size': [...]}`. The `v1`/`v2` labels are lost, and `<source_type>` (when present) falls out of alignment with the versions. We would have to parse `record.xml` with lxml ourselves anyway [5] | Parse `<version version="vN">` children directly |
| Fixture recording | Needs `responses` or vcrpy, because it uses requests | `httpx.MockTransport` (built in) or respx |
| Size | 0 lines of client code, but about 40 lines of subclass and workarounds, plus about 60 lines of parser | About 150 lines of client code plus about 60 lines of parser |

## 2. Shape of our own client (sketch only, not in src/)

```python
OAI = "{http://www.openarchives.org/OAI/2.0/}"
RAW = "{http://arxiv.org/OAI/arXivRaw/}"

class OaiError(Exception): code: str

@dataclass(frozen=True)
class Page:
    response_date: datetime            # parsed from <responseDate>, UTC
    records: list[etree._Element]      # <record> elements
    token: str | None                  # None or "" means the list is finished

class OaiClient:
    def __init__(self, http: httpx.Client, limiter: ArxivLimiter, base_url=BASE): ...

    def _get(self, params) -> etree._Element:
        for attempt in range(3):
            with self.limiter.slot():                  # fcntl lock file + last-request timestamp, sleep until 3 s have passed
                try:
                    r = self.http.get(self.base_url, params=params, timeout=60)
                except httpx.TransportError: wait = backoff(attempt); continue
            if r.status_code in (429, 503): wait = retry_after(r) or backoff(attempt); sleep(wait); continue
            r.raise_for_status()
            return etree.fromstring(r.content, parser=SAFE_PARSER)  # resolve_entities=False, no_network=True
        raise ArxivUnavailable(...)

    def list_records(self, set_: str, from_: date) -> Iterator[Page]:
        params = {"verb": "ListRecords", "metadataPrefix": "arXivRaw", "set": set_, "from": from_.isoformat()}
        while True:
            root = self._get(params)
            err = root.find(f"{OAI}error")
            if err is not None:
                if err.get("code") == "noRecordsMatch":
                    yield Page(rd(root), [], None); return
                raise OaiError(err.get("code"), err.text)      # badResumptionToken, badArgument, ...
            lr = root.find(f"{OAI}ListRecords")
            tok = lr.findtext(f"{OAI}resumptionToken")          # an empty element means this is the last page
            yield Page(rd(root), lr.findall(f"{OAI}record"), tok or None)
            if not tok: return
            params = {"verb": "ListRecords", "resumptionToken": tok}   # httpx re-encodes it; see section 3.4

def parse_arxivraw(record) -> RawPaper:   # id, versions[(n, submitted_at, size_kb, source_flag?)], title, authors,
    ...                                     # categories (space-separated, primary first), license, abstract, doi, journal-ref, comments
```

The `ArxivLimiter` belongs to spec §5's shared module, not to this client, so it is not counted in the line estimate above.

## 3. Live findings (confirmed by request and by the server source [6])

### 3.1 `from` / `until` semantics
- `from=D` becomes `D 00:00:00 UTC`, so it is **inclusive**. `until=D` becomes `D 23:59:59 UTC`, also inclusive. If `until` is omitted, it becomes today at 23:59:59 UTC [6, `requests/data_queries.py`].
- `datestamp` is the UTC date of `Metadata.modtime` for the current version [6, `serializers/create_records.py`]. The live check agreed: `from=2026-10-23` with no `until` on hep-lat returned 11 records, all with datestamp `2026-10-23`. That matched `from=until=2026-10-23` exactly, because the 24th and 25th were a weekend.
- A finer granularity is rejected: `from=2026-10-23T00:00:00Z` gives `badArgument`, "from date format must be YYYY-MM-DD".
- Datestamp follows announcement, not submission. For example, 2603.09977 v3 was submitted on `Thu, 22 Oct 2026 16:46:52 GMT` and has datestamp `2026-10-23`. 2510.13771 has datestamp 2026-10-23 but its latest version is from Sep 2026. That is a metadata-only edit (a journal-ref was added).

### 3.2 Empty window (`noRecordsMatch`)
The server returns **HTTP 200**, not 4xx, with a body like this (fixture `listrecords_norecordsmatch.xml`):
```xml
<responseDate>2026-10-25T10:36:19Z</responseDate>
<request verb="ListRecords" metadataPrefix="arXivRaw" from="2026-10-25" until="2026-10-25" set="physics:hep-lat">http://oaipmh.arxiv.org/oai</request>
<error code='noRecordsMatch'>The combination of the values of the from, until, set and metadataPrefix arguments results in an empty list.</error>
```
All OAI errors come back as HTTP 200 with `<error code=...>` [6, `factory.py`]. HTTP status codes therefore signal only transport or infrastructure problems.

### 3.3 `responseDate`
- The format is `YYYY-MM-DDThh:mm:ssZ` in UTC, for example `2026-10-25T10:36:14Z`.
- It is `datetime.now(utc)` at render time [6, `processors/fetch_list.py`].
- `Identify` is cached for a long time. Its live `responseDate` was `2026-10-14T11:08:16Z` on 2026-10-25. This confirms the spec rule never to take the high-water mark from Identify.

### 3.4 Paging and resumption tokens
- **Records per page:** ListRecords returned **1300 per page** live (cs.LG, 2026-10-15..23, 3316 records over 3 pages). The source default is `RECORDS_LIMIT=2500`, so production overrides it. ListIdentifiers allows up to 20000 per page [6, `config.py`]. Treat the page size as unknown.
- **Typical daily volume:** one day of cs.LG had 362 to 823 records and hep-lat had 11, so a normal daily run is a single page per set. The 14-day backfill takes a few pages.
- **Token format:** the token is a readable, URL-quoted query string: `verb=ListRecords&metadataPrefix=arXivRaw&from=2026-10-19&until=2026-10-23&set=cs%3Acs%3ALG&skip=371`. The server rewrites `from` to the last day on the page and sets `skip` to the number of that day's records it has already sent [6, `processors/resume.py`, `fetch_list.py`].
- **No overlap or gaps between pages:** across the 3 pages the identifier sets did not overlap, and the per-day counts matched a separate 3-day query (420, 398, 362).
- **Token attributes:** `expirationDate` is the next UTC midnight. There is no `cursor` and no `completeListSize`.
- **Last page:** the final page carries an empty `<resumptionToken/>` (fixture `..._page3_..._final-empty-token.xml`). A response that fits in one page has **no** token element at all (fixture `..._single-page.xml`).
- **Token encoding:** the token already contains `%3D`-style escapes. Passing it as a normal param (`params={"resumptionToken": tok}`) worked with curl. httpx encodes `%` to `%25`, and the server `unquote`s it, so that path also works.
- **Expired or invalid token:** the server replies with HTTP 200 and `<error code='badResumptionToken'>…Token decoding failed or format is invalid.</error>`. The right response is to restart the set from `from=hwm`, which is idempotent.

### 3.5 arXivRaw version history structure
```xml
<arXivRaw xmlns="http://arxiv.org/OAI/arXivRaw/">
  <id>2603.09977</id><submitter>Aleksey Cherman</submitter>
  <version version="v1"><date>Tue, 10 Mar 2026 17:59:59 GMT</date><size>111kb</size></version>
  <version version="v2"><date>Tue, 14 Apr 2026 20:07:05 GMT</date><size>499kb</size></version>
  <version version="v3"><date>Thu, 22 Oct 2026 16:46:52 GMT</date><size>331kb</size></version>
  <title>…</title><authors>…</authors><categories>hep-th hep-lat hep-ph nucl-th</categories>
  <comments>…</comments><journal-ref>…</journal-ref><doi>…</doi>
  <license>http://creativecommons.org/licenses/by/4.0/</license><abstract>…</abstract>
</arXivRaw>
```
- Every version is listed, oldest first. `<date>` is the **submission** time in RFC 2822 format; parse it with `email.utils.parsedate_to_datetime`.
- `<source_type>` is optional and sparse: 300 elements across 3316 cs.LG records. It holds single-letter flags (on page 1: 73 `D`, 20 `A`, 8 `I`), **not** latex/pdf [6, `templates/record_formats.xml`].
- The primary category is the first token in `<categories>`. The header `setSpec`s list every set the paper is in, including cross-lists.
- `Identify` reports `deletedRecord=persistent`, but the list template never emits `status="deleted"` headers. We cannot rely on seeing deletions.

### 3.6 CDN caching (Fastly/Varnish)
Responses are cached at the edge. A repeat of the same URL returned `x-cache: …HIT`, `age: 165`, and the **original** `responseDate` (10:36:19 at 10:39:03). The cache lifetimes come from `Surrogate-Control` in the server source [6]:

| Response | Cached for |
| --- | --- |
| A list whose window includes today (no `until`, as Watch uses) | 1 h |
| A list whose window is entirely in the past | 4 days, purged at announce |
| An OAI error, including `noRecordsMatch` | until the next UTC midnight |

Consequences for Watch:
- The high-water mark is still safe, because the stale `responseDate` is never later than the data in the response.
- The URL changes each day because `from=hwm` does, so a cached empty result does not carry over to the next run.
- A same-day re-run may receive the earlier response. The spec already treats a second run on the same day as harmless.
- We cannot cache-bust, because any extra query param is answered with `badArgument` [6, `data_queries.py`].

## 4. Rate-limit and backoff notes
- arXiv's ToU is followed by the spec's 3 s / single-connection limiter, as already known.
- I did not provoke 429 or 503 (that would have been impolite). Infrastructure errors come from Google Frontend or Fastly, so the client must accept `Retry-After` in both delta-seconds and HTTP-date form (RFC 9110 §10.2.3).
- Sickle crashes on the HTTP-date form (`int()` raises `ValueError`, and only `TypeError` is caught) [3].

## 5. Fixture-recording approach
| Option | Fit |
| --- | --- |
| **Raw `.xml` fixtures + `httpx.MockTransport`** | **Best.** No extra dependency. The handler routes on `request.url.params` (verb, resumptionToken) to a fixture file. Fixtures are plain XML: easy to diff and to trim by hand. |
| respx 0.23.1 (2026-04) [7] | Good. Same idea with a nicer route DSL. Worth adding only if more httpx mocks appear (the `/src/` fetch, Anthropic). |
| pytest-recording 0.14.0 / vcrpy 8.3.0 [8] | Poor fit. Cassettes are YAML with the body embedded, and real pages are 1 to 3.5 MB, so every cassette would need trimming anyway. Replaying in record mode against live arXiv in CI would break the ToU and the 3 s limit. |

To refresh fixtures, use a one-off script (`scripts/record_oai_fixture.py`). It makes one request through the real limiter, writes the body, and optionally trims to N records with a header comment, as done here.

**Fixtures saved** in `.scratch/m0/research/fixtures/` (all metadata; total about 41 KB):

| File | Contents |
| --- | --- |
| `listrecords_hep-lat_2026-10-23_single-page.xml` | Verbatim, 11 records, no token element. Includes a new-version case and a metadata-only edit. |
| `listrecords_norecordsmatch.xml` | Verbatim. |
| `listrecords_badresumptiontoken.xml` | Verbatim. |
| `listrecords_cs-LG_page2_trimmed_with-token.xml` | Page 2 of 3, trimmed to 2 records. Keeps the real token and `responseDate`. |
| `listrecords_cs-LG_page3_trimmed_final-empty-token.xml` | Last page, trimmed, ending with `<resumptionToken/>`. |

## Sources
1. PyPI Sickle JSON: https://pypi.org/pypi/Sickle/json (release history; 0.7.0 on 2020-05-17; deps `requests`, `lxml`)
2. https://github.com/mloesch/sickle (HEAD `14ef88e` "Release 0.7.0", 2020-05-17; 14 open issues per the GitHub API)
3. `sickle/app.py` at `14ef88e`: `harvest()`, `_request()`, `get_retry_after()`. https://github.com/mloesch/sickle/blob/master/sickle/app.py
4. `sickle/iterator.py` at `14ef88e`: `BaseOAIIterator._next_response`, `OAIItemIterator`
5. `sickle/utils.py` `xml_to_dict` and `sickle/models.py` `Record.get_metadata`. The flattening was verified by running sickle 0.7.0 on Python 3.13.14 against the saved hep-lat response.
6. arXiv's OAI-PMH server source, https://github.com/arXiv/oaipmh at `b94fd55` (2026-10-16): `oaipmh/config.py`, `requests/data_queries.py`, `processors/fetch_list.py`, `processors/resume.py`, `processors/db.py`, `factory.py`, `templates/record_formats.xml`, `templates/token.xml`
7. https://pypi.org/project/respx/ (0.23.1, 2026-04-08)
8. https://pypi.org/project/pytest-recording/ (0.14.0, 2026-10-01), https://pypi.org/project/vcrpy/ (8.3.0, 2026-07-04)
9. Live requests to https://oaipmh.arxiv.org/oai on 2026-10-25, 10:36 to 10:39 UTC (responses and headers as quoted above)
