"""`phy daily` with every HTTP request replayed: OAI-PMH, arXiv `/src/` and the Messages API."""

import json
import re
import sqlite3
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

import httpx
import pytest
import respx
from archives import tar_gz
from typer.testing import CliRunner

from phy import daily
from phy.cli import app
from phy.config import resolve_paths
from phy.locks import phy_lock
from phy.release import ReleaseStatus

FIXTURES = Path(__file__).parent / "fixtures"
OAI_URL = "https://oaipmh.arxiv.org/oai"
SRC_URL = re.compile(r"https://arxiv\.org/src/(?P<id>[\d.]+)v(?P<version>\d+)")
MESSAGES_URL = "https://api.anthropic.com/v1/messages"
HEP_LAT = (FIXTURES / "oai" / "listrecords_hep-lat_2026-10-23_single-page.xml").read_bytes()
NO_RECORDS = (FIXTURES / "oai" / "listrecords_norecordsmatch.xml").read_bytes()
FILTER = json.loads((FIXTURES / "anthropic" / "filter_1904.12072_response.json").read_text())
READ = json.loads((FIXTURES / "anthropic" / "read_1904.12072v3_response.json").read_text())
SOURCE = tar_gz(
    {"main.tex": b"\\documentclass{revtex4}\n\\begin{document}\nA flow.\n\\end{document}\n"}
)
PAPERS = 11  # in the hep-lat page, a set that skips the pre-filter; each scores 0.95
BROKEN = "2610.30341"


@pytest.fixture
def installed(phy_home, monkeypatch):
    phy_home.mkdir()
    for name in ["config.toml", "questions.yaml"]:
        (phy_home / name).write_bytes((files("phy") / "defaults" / name).read_bytes())
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr("phy.arxiv.time.sleep", lambda _: None)
    monkeypatch.setattr("anthropic._base_client.time.sleep", lambda _: None)
    return phy_home


class Api:
    """The replayed services; `broken` arXiv ids get a 404 from `/src/`."""

    def __init__(self):
        self.broken: set[str] = set()
        self.calls: list[str] = []  # the model of each Messages call

    def oai(self, request):
        first_page = request.url.params.get("set") == "physics:hep-lat"
        return httpx.Response(200, content=HEP_LAT if first_page else NO_RECORDS)

    def src(self, request, id, version):
        if id in self.broken:
            return httpx.Response(404)
        return httpx.Response(200, content=SOURCE)

    def messages(self, request):
        model = json.loads(request.content)["model"]
        self.calls.append(model)
        return httpx.Response(200, json=FILTER if model == "claude-haiku-5-5" else READ)


@pytest.fixture
def api():
    api = Api()
    with (
        respx.mock(assert_all_called=False) as arxiv,
        respx.mock(using="httpx2", assert_all_called=False) as anthropic,
    ):
        arxiv.get(OAI_URL).mock(side_effect=lambda request: api.oai(request))
        arxiv.get(url=SRC_URL).mock(side_effect=api.src)
        anthropic.post(MESSAGES_URL).mock(side_effect=api.messages)
        yield api


def phy(*args):
    return CliRunner().invoke(app, list(args))


def rows(phy_home, sql):
    conn = sqlite3.connect(phy_home / "phy.db")
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql)]
    finally:
        conn.close()


def events(phy_home):
    [log_file] = (phy_home / "logs").iterdir()
    return [json.loads(line) for line in log_file.read_text().splitlines()]


def test_daily_runs_the_four_stages_in_order(installed, api):
    api.broken.add(BROKEN)

    result = phy("daily")

    assert result.exit_code == 0, result.output
    assert len(rows(installed, "SELECT * FROM papers")) == PAPERS
    assert len(rows(installed, "SELECT * FROM screenings WHERE screened_in")) == PAPERS
    cards = rows(installed, "SELECT * FROM cards")
    assert len(cards) == PAPERS - 1
    assert BROKEN not in {c["arxiv_id"] for c in cards}
    assert {c["status"] for c in cards} == {"verified"}
    [failed] = rows(installed, "SELECT * FROM runs WHERE status = 'failed'")
    assert (failed["stage"], failed["arxiv_id"]) == ("read", BROKEN)
    assert "404" in failed["error"]

    logged = events(installed)
    finished = [e["event"] for e in logged if e["event"].endswith(".finished")]
    assert finished == [
        "watch.finished",
        "filter.finished",
        "read.finished",
        "verify.finished",
        "daily.finished",
    ]
    [error] = [e for e in logged if e["level"] == "error"]
    assert (error["event"], error["arxiv_id"]) == ("read.paper_failed", BROKEN)
    # migrations apply on the first run only; a normal day Cards about read.daily_quota (8)
    info = [e for e in logged if e["level"] == "info" and e["event"] != "db.migrated"]
    per_card = [e for e in info if e["event"] in ("read.card_written", "verify.card_verified")]
    assert len(per_card) == 2 * (PAPERS - 1)
    assert len(info) - len(per_card) + 2 * 8 <= 31  # "under about 30"


def test_the_next_daily_catches_up_and_a_third_does_nothing_new(installed, api):
    api.broken.add(BROKEN)
    assert phy("daily").exit_code == 0
    api.broken.clear()
    calls = len(api.calls)

    assert phy("daily").exit_code == 0
    assert api.calls[calls:] == ["claude-sonnet-5-5"]  # only the broken Paper is Read
    assert len(rows(installed, "SELECT * FROM cards WHERE status = 'verified'")) == PAPERS
    before = rows(installed, "SELECT * FROM cards")

    assert phy("daily").exit_code == 0
    assert len(api.calls) == calls + 1
    assert rows(installed, "SELECT * FROM cards") == before


def test_a_failed_stage_is_logged_and_the_later_stages_still_run(installed, api, monkeypatch):
    def oai_down(request):
        return httpx.Response(503)

    monkeypatch.setattr(api, "oai", oai_down)
    result = phy("daily")

    assert result.exit_code == 0, result.output
    stages = [r["stage"] for r in rows(installed, "SELECT * FROM runs ORDER BY rowid")]
    assert stages == ["watch", "filter", "read", "verify"]
    [error] = [e for e in events(installed) if e["level"] == "error"]
    assert (error["event"], error["stage"]) == ("daily.stage_failed", "watch")


def test_held_phy_lock_makes_daily_exit_zero_having_done_nothing(installed):
    with respx.mock() as router, phy_lock(resolve_paths()):
        result = phy("daily")

    assert result.exit_code == 0
    assert not router.calls
    assert not (installed / "phy.db").exists()


def test_read_without_paper_reads_the_selection_and_reports_failures(installed, api):
    assert phy("watch").exit_code == 0
    assert phy("filter").exit_code == 0
    api.broken.add(BROKEN)

    result = phy("read")

    assert result.exit_code == 1
    assert f"{PAPERS - 1} carded, 1 failed" in result.output
    assert f"failed: {BROKEN}v1" in result.output
    assert len(rows(installed, "SELECT * FROM cards WHERE status = 'draft'")) == PAPERS - 1


def test_dry_run_and_force_need_a_paper(installed):
    assert phy("read", "--dry-run").exit_code != 0
    assert phy("read", "--force").exit_code != 0


def test_a_bug_in_a_stage_runs_the_later_stages_then_fails_the_command(installed, api, monkeypatch):
    def watch_with_a_bug(ctx):
        raise KeyError("bug")

    monkeypatch.setattr(daily, "STAGES", [("watch", watch_with_a_bug, ()), *daily.STAGES[1:]])

    result = phy("daily")

    assert result.exit_code == 1
    stages = [r["stage"] for r in rows(installed, "SELECT * FROM runs ORDER BY rowid")]
    assert stages == ["filter", "read", "verify"]
    [error] = [e for e in events(installed) if e["level"] == "error"]
    assert error["event"] == "daily.stage_failed"
    assert "Traceback" in error["exception"]


def test_daily_logs_a_pending_release_and_records_when_it_ran(installed, api, monkeypatch):
    pending = ReleaseStatus("v0.1.0", "v0.2.0", ["Fix Verify", "Add /review"])
    monkeypatch.setattr(daily, "release_status", lambda paths: pending)

    assert phy("daily").exit_code == 0

    [update] = [e for e in events(installed) if e["event"] == "schedule.update_available"]
    assert update["level"] == "info"
    assert (update["installed"], update["release"], update["commits"]) == ("v0.1.0", "v0.2.0", 2)
    [state] = rows(installed, "SELECT value FROM state WHERE key = 'daily.last_run_at'")
    assert state["value"].startswith(datetime.now(UTC).date().isoformat())


def test_daily_logs_nothing_about_releases_when_none_is_pending(installed, api):
    assert phy("daily").exit_code == 0
    assert "schedule.update_available" not in {e["event"] for e in events(installed)}
