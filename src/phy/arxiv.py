"""All arXiv traffic: one `httpx` client behind the shared rate limiter (SPEC §5).

`Arxiv.get()` makes one request at a time, at least `arxiv.min_interval_s` apart across
processes: it holds `arxiv.lock`, which keeps the time of the last request, for the request and
any backoff sleeps. 429, 503 and network errors are retried with exponential backoff, up to
`arxiv.max_retries` attempts in all; then `ArxivUnavailable` fails the Stage run.

OAI-PMH errors come back as HTTP 200 with `<error code=…>`; `parse_page()` raises them as
`OaiError` subclasses, except `noRecordsMatch`, which is an empty page. `parse_arxiv_raw()` turns
one `<record>` into an `ArxivRecord`; Read and Watch upsert from it the same way.
"""

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime

import httpx
import structlog
from lxml import etree

import phy
from phy.config import ArxivConfig, Paths
from phy.locks import arxiv_lock

log = structlog.get_logger()

OAI_URL = "https://oaipmh.arxiv.org/oai"
SRC_URL = "https://arxiv.org/src/{arxiv_id}v{version}"
OAI = "{http://www.openarchives.org/OAI/2.0/}"
RAW = "{http://arxiv.org/OAI/arXivRaw/}"
SAFE_XML = etree.XMLParser(resolve_entities=False, no_network=True)

RETRY_STATUS = {429, 503}
BACKOFF_BASE_S = 5.0
MAX_RETRY_AFTER_S = 300.0
TIMEOUT = httpx.Timeout(120.0, connect=20.0)


class ArxivUnavailable(Exception):
    """arXiv kept failing with 429, 503 or network errors through every attempt."""


class OaiError(Exception):
    """An OAI-PMH `<error code=…>` other than `noRecordsMatch`."""

    def __init__(self, code: str, message: str):
        super().__init__(f"OAI-PMH {code}: {message}")
        self.code = code


class IdDoesNotExist(OaiError):
    pass


class BadResumptionToken(OaiError):
    """The token expired (at UTC midnight) or is invalid; restart the set from the mark."""


OAI_ERRORS = {"idDoesNotExist": IdDoesNotExist, "badResumptionToken": BadResumptionToken}


@dataclass(frozen=True)
class Version:
    number: int
    submitted_at: datetime


@dataclass(frozen=True)
class ArxivRecord:
    """One arXivRaw record. `datestamp` is the OAI header datestamp of the harvest."""

    arxiv_id: str
    datestamp: date
    sets: list[str]
    title: str
    authors: str
    abstract: str
    categories: list[str]
    license: str | None
    versions: list[Version]

    @property
    def primary_category(self) -> str:
        return self.categories[0]

    @property
    def latest_version(self) -> int:
        return max(v.number for v in self.versions)


@dataclass(frozen=True)
class OaiPage:
    response_date: datetime
    records: list[ArxivRecord]
    token: str | None  # None on the last page


class Arxiv:
    def __init__(
        self,
        paths: Paths,
        config: ArxivConfig,
        http: httpx.Client | None = None,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ):
        self.paths = paths
        self.config = config
        self.http = http or httpx.Client(
            timeout=TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": f"phy-agent-platform/{phy.version()}"},
        )
        self.clock = clock or time.time
        self.sleep = sleep or time.sleep

    def __enter__(self) -> "Arxiv":
        return self

    def __exit__(self, *exc) -> None:
        self.http.close()

    def get(self, url: str, params: dict[str, str] | None = None) -> httpx.Response:
        """GET `url` through the rate limiter. Raises `httpx.HTTPStatusError` on other 4xx/5xx."""
        with arxiv_lock(self.paths) as slot:
            for attempt in range(1, self.config.max_retries + 1):
                if slot.last_request_at is not None:
                    wait = slot.last_request_at + self.config.min_interval_s - self.clock()
                    if wait > 0:
                        log.debug("arxiv.waited", wait_s=round(wait, 2))
                        self.sleep(wait)
                slot.mark(self.clock())
                response = None
                try:
                    response = self.http.get(url, params=params)
                except httpx.TransportError as e:
                    failure = f"{type(e).__name__}: {e}"
                else:
                    if response.status_code not in RETRY_STATUS:
                        response.raise_for_status()
                        log.debug("arxiv.fetched", url=url, status=response.status_code)
                        return response
                    failure = f"HTTP {response.status_code}"
                if attempt == self.config.max_retries:
                    break
                backoff = _retry_after(response) or BACKOFF_BASE_S * 2 ** (attempt - 1)
                log.warning("arxiv.retry", url=url, attempt=attempt, error=failure, wait_s=backoff)
                self.sleep(backoff)
        raise ArxivUnavailable(f"{url}: {failure} after {self.config.max_retries} attempts")

    def oai(self, params: dict[str, str]) -> OaiPage:
        return parse_page(self.get(OAI_URL, params=params).content)

    def get_record(self, arxiv_id: str) -> ArxivRecord:
        page = self.oai(
            {
                "verb": "GetRecord",
                "metadataPrefix": "arXivRaw",
                "identifier": f"oai:arXiv.org:{arxiv_id}",
            }
        )
        if len(page.records) != 1:
            raise OaiError("unexpectedResponse", f"GetRecord returned {len(page.records)} records")
        return page.records[0]

    def list_records(self, set_spec: str, from_: date) -> Iterator[OaiPage]:
        """Every page of one set from `from_` (inclusive, no `until`), following resumption
        tokens to the end. Tokens expire at the next UTC midnight, so they are never stored."""
        params = {
            "verb": "ListRecords",
            "metadataPrefix": "arXivRaw",
            "set": set_spec,
            "from": from_.isoformat(),
        }
        while True:
            page = self.oai(params)
            yield page
            if page.token is None:
                return
            params = {"verb": "ListRecords", "resumptionToken": page.token}

    def get_source(self, arxiv_id: str, version: int) -> bytes:
        return self.get(SRC_URL.format(arxiv_id=arxiv_id, version=version)).content


def _retry_after(response: httpx.Response | None) -> float | None:
    """`Retry-After` in seconds, from either delta-seconds or an HTTP-date (RFC 9110 §10.2.3)."""
    value = response.headers.get("Retry-After") if response is not None else None
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
        except (TypeError, ValueError):
            return None
    return min(max(seconds, 0.0), MAX_RETRY_AFTER_S) or None


def parse_page(content: bytes) -> OaiPage:
    root = etree.fromstring(content, parser=SAFE_XML)
    response_date = datetime.fromisoformat(root.findtext(f"{OAI}responseDate").strip())
    error = root.find(f"{OAI}error")
    if error is not None:
        code = error.get("code", "")
        if code == "noRecordsMatch":
            return OaiPage(response_date=response_date, records=[], token=None)
        raise OAI_ERRORS.get(code, OaiError)(code, (error.text or "").strip())
    # A single-page list has no token element; the last page of a longer one has an empty one.
    token = (root.findtext(f".//{OAI}resumptionToken") or "").strip()
    return OaiPage(
        response_date=response_date,
        records=[parse_arxiv_raw(r) for r in root.iter(f"{OAI}record")],
        token=token or None,
    )


def parse_arxiv_raw(record: etree._Element) -> ArxivRecord:
    header = record.find(f"{OAI}header")
    raw = record.find(f"{OAI}metadata/{RAW}arXivRaw")

    def text(tag: str) -> str:
        return " ".join((raw.findtext(f"{RAW}{tag}") or "").split())

    return ArxivRecord(
        arxiv_id=text("id"),
        datestamp=date.fromisoformat(header.findtext(f"{OAI}datestamp").strip()),
        sets=[s.text.strip() for s in header.iter(f"{OAI}setSpec")],
        title=text("title"),
        authors=text("authors"),
        abstract=text("abstract"),
        categories=text("categories").split(),
        license=text("license") or None,
        versions=[
            Version(
                number=int(v.get("version").removeprefix("v")),
                submitted_at=parsedate_to_datetime(v.findtext(f"{RAW}date")).astimezone(UTC),
            )
            for v in raw.iter(f"{RAW}version")
        ],
    )
