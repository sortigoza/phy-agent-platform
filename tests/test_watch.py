import json
import re
import sqlite3
from datetime import date
from importlib.resources import files
from pathlib import Path

import httpx
import pytest
import respx
from oai import Rec, page
from typer.testing import CliRunner

from phy.cli import app
from phy.config import resolve_paths
from phy.locks import phy_lock

FIXTURES = Path(__file__).parent / "fixtures" / "oai"
OAI_URL = "https://oaipmh.arxiv.org/oai"
TODAY = date(2026, 10, 25)
V1 = "Mon, 19 Oct 2026 12:00:00 GMT"
V2 = "Thu, 22 Oct 2026 12:00:00 GMT"


def fixture(name):
    return (FIXTURES / name).read_bytes()


def install(phy_home, sets):
    """The default config with `watch.sets` replaced by `sets`."""
    config = (files("phy") / "defaults" / "config.toml").read_text()
    prefilter = "".join(f'"{s}" = "none"\n' for s in sets)
    watch = (
        f"[watch]\nbackfill_days = 14\nsets = {sets!r}\n\n[watch.prefilter]\n{prefilter}\n"
    ).replace("'", '"')
    (phy_home / "config.toml").write_text(
        re.sub(r"\[watch\].*?(?=\[arxiv\])", watch, config, flags=re.S)
    )
    (phy_home / "questions.yaml").write_bytes(
        (files("phy") / "defaults" / "questions.yaml").read_bytes()
    )


@pytest.fixture
def installed(phy_home, monkeypatch):
    phy_home.mkdir()
    install(phy_home, ["physics:hep-lat"])
    monkeypatch.setattr("phy.arxiv.time.sleep", lambda _: None)
    monkeypatch.setattr("phy.watch.utc_today", lambda: TODAY)
    return phy_home


def serve(router, first_pages, by_token=None):
    """Answer ListRecords: the first page by `set`, later pages by `resumptionToken`."""
    by_token = by_token or {}

    def oai(request):
        params = dict(request.url.params)
        if "resumptionToken" in params:
            return _response(by_token[params["resumptionToken"]])
        return _response(first_pages[params["set"]])

    return router.get(OAI_URL).mock(side_effect=oai)


def _response(content):
    if isinstance(content, httpx.Response):
        return content
    return httpx.Response(200, content=content)


def phy(*args):
    return CliRunner().invoke(app, list(args))


def rows(phy_home, sql):
    conn = sqlite3.connect(phy_home / "phy.db")
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql)]
    finally:
        conn.close()


def state(phy_home, key):
    found = rows(phy_home, f"SELECT value FROM state WHERE key = '{key}'")
    return found[0]["value"] if found else None


def test_first_run_backfills_and_sets_the_mark(installed):
    with respx.mock() as router:
        route = serve(
            router, {"physics:hep-lat": fixture("listrecords_hep-lat_2026-10-23_single-page.xml")}
        )
        result = phy("watch")

    assert result.exit_code == 0, result.output
    assert dict(route.calls.last.request.url.params) == {
        "verb": "ListRecords",
        "metadataPrefix": "arXivRaw",
        "set": "physics:hep-lat",
        "from": "2026-10-11",
    }
    assert len(rows(installed, "SELECT * FROM papers")) == 11
    assert state(installed, "watch.hwm") == "2026-10-25"
    assert state(installed, "watch.last_success_at")
    [run] = rows(installed, "SELECT * FROM runs")
    assert run["stage"] == "watch"
    assert run["status"] == "ok"
    assert run["ended_at"]


def set_mark(phy_home, value):
    conn = sqlite3.connect(phy_home / "phy.db")
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO state (key, value, updated_at) VALUES ('watch.hwm', ?, '')",
            (value,),
        )
    conn.close()


def harvested_once(phy_home):
    """Run Watch once on an empty window, so the db exists and the mark is today."""
    with respx.mock() as router:
        serve(router, {"physics:hep-lat": fixture("listrecords_norecordsmatch.xml")})
        assert phy("watch").exit_code == 0


def test_two_pages_via_a_resumption_token(installed):
    install(installed, ["cs:cs:LG"])
    second = fixture("listrecords_cs-LG_page2_trimmed_with-token.xml")
    token = re.search(rb"<resumptionToken[^>]*>([^<]+)<", second).group(1).decode()
    with respx.mock() as router:
        route = serve(
            router,
            {"cs:cs:LG": second},
            {token: fixture("listrecords_cs-LG_page3_trimmed_final-empty-token.xml")},
        )
        result = phy("watch")

    assert result.exit_code == 0, result.output
    assert route.call_count == 2
    assert len(rows(installed, "SELECT * FROM papers")) == 4
    assert state(installed, "watch.hwm") == "2026-10-25"


def test_no_records_match_is_a_successful_empty_run(installed):
    harvested_once(installed)

    assert rows(installed, "SELECT * FROM papers") == []
    assert state(installed, "watch.hwm") == "2026-10-25"
    assert [r["status"] for r in rows(installed, "SELECT * FROM runs")] == ["ok"]


def test_bad_resumption_token_fails_the_run_and_leaves_the_mark(installed):
    harvested_once(installed)
    set_mark(installed, "2026-10-20")
    with respx.mock() as router:
        serve(
            router,
            {"physics:hep-lat": page([Rec("2610.00001", [V1])], token="t1")},
            {"t1": fixture("listrecords_badresumptiontoken.xml")},
        )
        result = phy("watch")

    assert result.exit_code == 1
    assert "badResumptionToken" in result.output
    assert state(installed, "watch.hwm") == "2026-10-20"
    failed = rows(installed, "SELECT * FROM runs WHERE status = 'failed'")
    assert len(failed) == 1
    assert "badResumptionToken" in failed[0]["error"]


def test_the_mark_stays_unless_every_set_succeeds(installed):
    install(installed, ["physics:hep-lat", "physics:quant-ph"])
    first_pages = {
        "physics:hep-lat": page([Rec("2610.00001", [V1])], response_date="2026-10-25T09:00:00Z"),
        "physics:quant-ph": httpx.Response(503),
    }
    with respx.mock() as router:
        serve(router, first_pages)
        result = phy("watch")

    assert result.exit_code == 1
    assert state(installed, "watch.hwm") is None
    assert state(installed, "watch.last_success_at") is None
    # The first set's upserts stand; the next run fetches them again for free.
    assert len(rows(installed, "SELECT * FROM papers")) == 1


# The `cards` table arrives with the Read call (migration 003_cards); until then the tests make
# the SPEC §6 columns Watch touches.
CARDS = (
    "CREATE TABLE IF NOT EXISTS cards (id INTEGER PRIMARY KEY, arxiv_id TEXT NOT NULL,"
    " version INTEGER NOT NULL, card_json TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL)"
)


def add_card(phy_home, arxiv_id, version, status="reviewed"):
    conn = sqlite3.connect(phy_home / "phy.db")
    with conn:
        conn.execute(CARDS)
        conn.execute(
            "INSERT INTO cards (arxiv_id, version, status) VALUES (?, ?, ?)",
            (arxiv_id, version, status),
        )
    conn.close()


def watch_with(phy_home, first_pages):
    with respx.mock() as router:
        serve(router, first_pages)
        result = phy("watch")
    assert result.exit_code == 0, result.output


def set_counts(phy_home):
    """The `watch.set_harvested` events logged so far, oldest first."""
    [log_file] = (phy_home / "logs").glob("*.jsonl")
    events = [json.loads(line) for line in log_file.read_text().splitlines()]
    keys = ["set", "records", "new_papers", "new_versions", "metadata_only", "unchanged"]
    return [{k: e[k] for k in keys} for e in events if e["event"] == "watch.set_harvested"]


def test_new_paper_new_version_and_metadata_only_change_are_told_apart(installed):
    install(installed, ["physics:hep-lat", "physics:quant-ph"])
    watch_with(
        installed,
        {
            "physics:hep-lat": page([Rec("2610.00001", [V1]), Rec("2610.00002", [V1])]),
            "physics:quant-ph": page([]),
        },
    )
    add_card(installed, "2610.00001", 1)
    add_card(installed, "2610.00002", 1)

    watch_with(
        installed,
        {
            "physics:hep-lat": page(
                [
                    Rec("2610.00001", [V1, V2], datestamp="2026-10-26"),
                    Rec("2610.00002", [V1], datestamp="2026-10-26", title="Retitled"),
                ]
            ),
            # Cross-listed: the same Paper again from another set.
            "physics:quant-ph": page(
                [
                    Rec(
                        "2610.00002",
                        [V1],
                        datestamp="2026-10-26",
                        title="Retitled",
                        sets=["physics:quant-ph"],
                    ),
                    Rec("2610.00003", [V1], datestamp="2026-10-26", sets=["physics:quant-ph"]),
                ]
            ),
        },
    )

    assert set_counts(installed)[2:] == [
        {
            "set": "physics:hep-lat",
            "records": 2,
            "new_papers": 0,
            "new_versions": 1,
            "metadata_only": 1,
            "unchanged": 0,
        },
        {
            "set": "physics:quant-ph",
            "records": 2,
            "new_papers": 1,
            "new_versions": 0,
            "metadata_only": 1,  # the Paper gains a set
            "unchanged": 0,
        },
    ]
    papers = {p["arxiv_id"]: p for p in rows(installed, "SELECT * FROM papers")}
    assert papers["2610.00001"]["latest_version"] == 2
    assert papers["2610.00002"]["title"] == "Retitled"
    assert papers["2610.00002"]["sets"] == "physics:hep-lat physics:quant-ph"
    versions = rows(
        installed,
        "SELECT arxiv_id, version, first_seen_datestamp FROM paper_versions ORDER BY 1, 2",
    )
    assert [tuple(v.values()) for v in versions] == [
        ("2610.00001", 1, "2026-10-23"),
        ("2610.00001", 2, "2026-10-26"),
        ("2610.00002", 1, "2026-10-23"),
        ("2610.00003", 1, "2026-10-26"),
    ]
    cards = rows(installed, "SELECT arxiv_id, status FROM cards ORDER BY arxiv_id")
    assert [tuple(c.values()) for c in cards] == [
        ("2610.00001", "stale"),
        ("2610.00002", "reviewed"),
    ]


def test_re_running_the_same_window_changes_nothing(installed):
    hep_lat = {"physics:hep-lat": fixture("listrecords_hep-lat_2026-10-23_single-page.xml")}
    watch_with(installed, hep_lat)
    counts = [
        rows(installed, f"SELECT count(*) AS n FROM {t}")[0]["n"]
        for t in ["papers", "paper_versions"]
    ]

    watch_with(installed, hep_lat)

    assert [
        rows(installed, f"SELECT count(*) AS n FROM {t}")[0]["n"]
        for t in ["papers", "paper_versions"]
    ] == counts
    assert set_counts(installed)[-1]["unchanged"] == 11


def from_dates(phy_home, *args, response_date="2026-10-25T10:00:00Z"):
    """Run `phy watch *args` on an empty window; the `from` it asked for and the mark after."""
    with respx.mock() as router:
        route = serve(router, {"physics:hep-lat": page([], response_date=response_date)})
        result = phy("watch", *args)
    assert result.exit_code == 0, result.output
    return route.calls.last.request.url.params["from"], state(phy_home, "watch.hwm")


def test_a_run_starts_from_the_mark(installed):
    harvested_once(installed)
    set_mark(installed, "2026-10-21")

    assert from_dates(installed) == ("2026-10-21", "2026-10-25")


def test_since_before_the_mark_re_harvests_without_moving_the_mark_backwards(installed):
    harvested_once(installed)

    assert from_dates(installed, "--since", "2026-10-01", response_date="2026-10-24T10:00:00Z") == (
        "2026-10-01",
        "2026-10-25",
    )


def test_since_after_the_mark_leaves_the_gap_and_the_mark(installed):
    harvested_once(installed)
    set_mark(installed, "2026-10-10")

    assert from_dates(installed, "--since", "2026-10-20") == ("2026-10-20", "2026-10-10")
    assert state(installed, "watch.last_success_at")


def test_reset_clears_the_mark_and_backfills(installed):
    harvested_once(installed)
    set_mark(installed, "2026-10-21")

    assert from_dates(installed, "--reset", response_date="2026-10-25T08:00:00Z") == (
        "2026-10-11",
        "2026-10-25",
    )


def test_since_and_reset_cannot_be_combined(installed):
    with respx.mock() as router:
        result = phy("watch", "--reset", "--since", "2026-10-01")

    assert result.exit_code != 0
    assert not router.calls


def test_held_phy_lock_makes_watch_exit_zero_without_harvesting(installed):
    with respx.mock() as router, phy_lock(resolve_paths()):
        result = phy("watch")

    assert result.exit_code == 0
    assert not router.calls
    assert not (installed / "phy.db").exists()
