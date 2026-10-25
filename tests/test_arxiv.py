import threading
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
import respx

from phy.arxiv import (
    Arxiv,
    ArxivUnavailable,
    BadResumptionToken,
    IdDoesNotExist,
    OaiError,
    parse_page,
)
from phy.config import ArxivConfig, resolve_paths

URL = "https://arxiv.org/src/1904.12072v3"
CONFIG = ArxivConfig(min_interval_s=3.0, max_retries=3)


class FakeTime:
    """A clock that only moves when someone sleeps. Shared by every client in a test."""

    def __init__(self, start=1_000_000.0):
        self.now = start
        self.sleeps = []
        self._lock = threading.Lock()

    def clock(self):
        return self.now

    def sleep(self, seconds):
        with self._lock:
            self.sleeps.append(seconds)
            self.now += seconds


@pytest.fixture
def paths(phy_home):
    phy_home.mkdir()
    return resolve_paths()


def client(paths, time):
    return Arxiv(paths, CONFIG, clock=time.clock, sleep=time.sleep)


def test_requests_from_two_clients_are_at_least_3s_apart(paths):
    time = FakeTime()
    sent_at = []
    with respx.mock() as router:
        router.get(URL).mock(side_effect=lambda _: sent_at.append(time.now) or httpx.Response(200))
        # Each client opens arxiv.lock itself, as a separate process would.
        threads = [threading.Thread(target=client(paths, time).get, args=(URL,)) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert len(sent_at) == 2
    assert abs(sent_at[1] - sent_at[0]) >= 3.0


def test_a_new_client_waits_out_the_interval_recorded_in_the_lock_file(paths):
    first = FakeTime(start=1000.0)
    second = FakeTime(start=1001.0)
    with respx.mock() as router:
        router.get(URL).mock(return_value=httpx.Response(200))
        client(paths, first).get(URL)
        client(paths, second).get(URL)

    assert first.sleeps == []
    assert second.sleeps == [pytest.approx(2.0)]


def test_503_is_retried_then_succeeds(paths):
    time = FakeTime()
    with respx.mock() as router:
        route = router.get(URL).mock(
            side_effect=[httpx.Response(503), httpx.Response(200, content=b"ok")]
        )
        response = client(paths, time).get(URL)

    assert response.content == b"ok"
    assert route.call_count == 2
    assert sum(time.sleeps) >= 3.0


def test_retry_after_seconds_is_honoured(paths):
    time = FakeTime()
    with respx.mock() as router:
        router.get(URL).mock(
            side_effect=[httpx.Response(429, headers={"Retry-After": "40"}), httpx.Response(200)]
        )
        client(paths, time).get(URL)

    assert 40 in time.sleeps


def test_network_errors_are_retried(paths):
    time = FakeTime()
    with respx.mock() as router:
        route = router.get(URL).mock(side_effect=[httpx.ConnectError("down"), httpx.Response(200)])
        client(paths, time).get(URL)

    assert route.call_count == 2


def test_three_failures_raise(paths):
    time = FakeTime()
    with respx.mock() as router:
        route = router.get(URL).mock(return_value=httpx.Response(503))
        with pytest.raises(ArxivUnavailable):
            client(paths, time).get(URL)

    assert route.call_count == 3


def test_other_http_errors_are_not_retried(paths):
    time = FakeTime()
    with respx.mock() as router:
        route = router.get(URL).mock(return_value=httpx.Response(404))
        with pytest.raises(httpx.HTTPStatusError):
            client(paths, time).get(URL)

    assert route.call_count == 1


FIXTURES = Path(__file__).parent / "fixtures" / "oai"
OAI_URL = "https://oaipmh.arxiv.org/oai"


def fixture(name):
    return (FIXTURES / name).read_bytes()


def test_parser_reads_every_record_on_the_hep_lat_page():
    page = parse_page(fixture("listrecords_hep-lat_2026-10-23_single-page.xml"))

    assert page.response_date == datetime(2026, 10, 25, 10, 36, 14, tzinfo=UTC)
    assert page.token is None
    assert len(page.records) == 11
    first = page.records[0]
    assert first.arxiv_id == "2510.13771"
    assert first.title == (
        "First simultaneous analysis of transverse momentum dependent and collinear parton"
        " distributions in the proton"
    )
    assert first.authors.startswith("P. C. Barry, A. Prokudin, T. Anderson")
    assert first.abstract.startswith("We present the first simultaneous global QCD analysis")
    assert first.categories == ["hep-ph", "hep-ex", "hep-lat", "nucl-th"]
    assert first.primary_category == "hep-ph"
    assert first.license == "http://arxiv.org/licenses/nonexclusive-distrib/1.0/"
    assert first.sets == ["physics:hep-ph", "physics:hep-ex", "physics:hep-lat", "physics:nucl-th"]
    assert first.datestamp == date(2026, 10, 23)
    assert [(v.number, v.submitted_at) for v in first.versions] == [
        (1, datetime(2025, 10, 15, 17, 22, 2, tzinfo=UTC)),
        (2, datetime(2026, 9, 16, 4, 23, 27, tzinfo=UTC)),
    ]
    assert first.latest_version == 2


def test_resumption_token_is_kept_and_an_empty_one_ends_the_list():
    with_token = parse_page(fixture("listrecords_cs-LG_page2_trimmed_with-token.xml"))
    last = parse_page(fixture("listrecords_cs-LG_page3_trimmed_final-empty-token.xml"))

    assert with_token.token.startswith("verb%3DListRecords")
    assert len(with_token.records) == 2
    assert last.token is None
    assert len(last.records) == 2


def test_no_records_match_is_an_empty_page():
    page = parse_page(fixture("listrecords_norecordsmatch.xml"))

    assert page.records == []
    assert page.token is None
    assert page.response_date == datetime(2026, 10, 25, 10, 36, 19, tzinfo=UTC)


def test_oai_errors_are_typed():
    with pytest.raises(BadResumptionToken) as e:
        parse_page(fixture("listrecords_badresumptiontoken.xml"))
    assert e.value.code == "badResumptionToken"
    assert isinstance(e.value, OaiError)


def test_get_record_fetches_arxivraw_metadata(paths):
    with respx.mock() as router:
        route = router.get(OAI_URL).mock(
            return_value=httpx.Response(200, content=fixture("getrecord_1904.12072.xml"))
        )
        record = client(paths, FakeTime()).get_record("1904.12072")

    assert dict(route.calls.last.request.url.params) == {
        "verb": "GetRecord",
        "metadataPrefix": "arXivRaw",
        "identifier": "oai:arXiv.org:1904.12072",
    }
    assert record.title == (
        "Flow-based generative models for Markov chain Monte Carlo in lattice field theory"
    )
    assert record.authors == "M. S. Albergo, G. Kanwar, P. E. Shanahan"
    assert record.latest_version == 3
    assert record.primary_category == "hep-lat"


def test_get_record_for_an_unknown_id_raises(paths):
    with respx.mock() as router:
        router.get(OAI_URL).mock(
            return_value=httpx.Response(200, content=fixture("getrecord_iddoesnotexist.xml"))
        )
        with pytest.raises(IdDoesNotExist):
            client(paths, FakeTime()).get_record("9999.99999")


def test_list_records_follows_the_resumption_token_to_the_empty_one(paths):
    def oai(request):
        params = dict(request.url.params)
        if "resumptionToken" in params:
            assert set(params) == {"verb", "resumptionToken"}
            return httpx.Response(
                200, content=fixture("listrecords_cs-LG_page3_trimmed_final-empty-token.xml")
            )
        return httpx.Response(
            200, content=fixture("listrecords_cs-LG_page2_trimmed_with-token.xml")
        )

    with respx.mock() as router:
        route = router.get(OAI_URL).mock(side_effect=oai)
        pages = list(client(paths, FakeTime()).list_records("cs:cs:LG", date(2026, 10, 19)))

    assert dict(route.calls[0].request.url.params) == {
        "verb": "ListRecords",
        "metadataPrefix": "arXivRaw",
        "set": "cs:cs:LG",
        "from": "2026-10-19",
    }
    assert route.calls[1].request.url.params["resumptionToken"].startswith("verb%3DListRecords")
    assert [len(p.records) for p in pages] == [2, 2]
    assert pages[0].response_date == datetime(2026, 10, 25, 10, 38, 29, tzinfo=UTC)
