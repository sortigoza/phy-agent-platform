"""Hand-built OAI-PMH ListRecords pages in arXivRaw, for Watch tests."""

from dataclasses import dataclass, field
from xml.sax.saxutils import escape


@dataclass
class Rec:
    arxiv_id: str
    versions: list[str]  # one RFC 2822 submission date per version, v1 first
    datestamp: str = "2026-10-23"
    sets: list[str] = field(default_factory=lambda: ["physics:hep-lat"])
    title: str = "A lattice paper"
    authors: str = "A. Author, B. Author"
    abstract: str = "We study a lattice."
    categories: str = "hep-lat"


def page(records: list[Rec], response_date="2026-10-25T10:36:14Z", token=None) -> bytes:
    """`token=None` gives a single-page list (no token element), `""` an empty final token."""
    body = "".join(_record(r) for r in records)
    if token is not None:
        body += f"<resumptionToken>{escape(token)}</resumptionToken>"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">'
        f"<responseDate>{response_date}</responseDate>"
        '<request verb="ListRecords">http://oaipmh.arxiv.org/oai</request>'
        f"<ListRecords>{body}</ListRecords></OAI-PMH>"
    ).encode()


def _record(r: Rec) -> str:
    sets = "".join(f"<setSpec>{s}</setSpec>" for s in r.sets)
    versions = "".join(
        f'<version version="v{n}"><date>{d}</date></version>'
        for n, d in enumerate(r.versions, start=1)
    )
    return (
        f"<record><header><identifier>oai:arXiv.org:{r.arxiv_id}</identifier>"
        f"<datestamp>{r.datestamp}</datestamp>{sets}</header>"
        '<metadata><arXivRaw xmlns="http://arxiv.org/OAI/arXivRaw/">'
        f"<id>{r.arxiv_id}</id>{versions}<title>{escape(r.title)}</title>"
        f"<authors>{escape(r.authors)}</authors><categories>{r.categories}</categories>"
        f"<abstract>{escape(r.abstract)}</abstract></arXivRaw></metadata></record>"
    )
