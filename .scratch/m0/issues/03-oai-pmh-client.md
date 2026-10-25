# OAI-PMH client: sickle or hand-rolled?

Type: research
Status: claimed
Blocked by: —

## Question

Should Watch use the `sickle` library or a hand-rolled `httpx` + `lxml` client for `oaipmh.arxiv.org/oai`? Judge each against:
- the shared rate limiter (≥ 3 s between requests, one connection, coordinated across processes through a lock file);
- resumption tokens that expire at UTC midnight;
- `arXivRaw` parsing, including the version history;
- `noRecordsMatch`, and error handling with backoff on 429 and 503;
- how easy it is to record real responses as test fixtures.

Also confirm the exact `responseDate` and datestamp semantics the high-water mark depends on. Check that `from` is inclusive, and how an empty day is reported. Use live requests at a polite rate.
