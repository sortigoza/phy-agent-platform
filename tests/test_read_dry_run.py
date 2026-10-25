import gzip
import hashlib
import json
import sqlite3
from importlib.resources import files
from pathlib import Path

import httpx
import pytest
import respx
from archives import tar_gz
from typer.testing import CliRunner

from phy.cli import app
from phy.config import resolve_paths
from phy.locks import phy_lock

FIXTURES = Path(__file__).parent / "fixtures" / "oai"
OAI_URL = "https://oaipmh.arxiv.org/oai"
SRC_URL = "https://arxiv.org/src/1904.12072v3"
COUNT_TOKENS_URL = "https://api.anthropic.com/v1/messages/count_tokens"
MAIN_TEX = (
    b"\\documentclass{revtex4}\n\\begin{document}\n% draft note\n"
    b"\\input{sections/intro}\nWe train a flow.\n\\end{document}\n"
)


SOURCE = tar_gz({"main.tex": MAIN_TEX, "sections/intro.tex": b"Lattice field theory.\n"})


@pytest.fixture
def installed(phy_home, monkeypatch):
    phy_home.mkdir()
    for name in ["config.toml", "questions.yaml"]:
        (phy_home / name).write_bytes((files("phy") / "defaults" / name).read_bytes())
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr("phy.arxiv.time.sleep", lambda _: None)
    return phy_home


@pytest.fixture
def arxiv():
    with respx.mock() as router:
        router.get(OAI_URL).mock(
            return_value=httpx.Response(
                200, content=(FIXTURES / "getrecord_1904.12072.xml").read_bytes()
            )
        )
        router.get(SRC_URL).mock(return_value=httpx.Response(200, content=SOURCE))
        yield router


@pytest.fixture
def anthropic_api():
    with respx.mock(using="httpx2") as router:
        route = router.post(COUNT_TOKENS_URL).mock(
            return_value=httpx.Response(200, json={"input_tokens": 1234})
        )
        yield route


def phy(*args):
    return CliRunner().invoke(app, list(args))


def rows(phy_home, sql):
    conn = sqlite3.connect(phy_home / "phy.db")
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql)]
    finally:
        conn.close()


def test_dry_run_registers_the_paper_and_writes_flattened_text(installed, arxiv, anthropic_api):
    result = phy("read", "--paper", "1904.12072", "--dry-run")

    assert result.exit_code == 0, result.output
    flattened = installed / "papers" / "1904.12072v3" / "flattened.txt"
    text = flattened.read_text()
    assert "Lattice field theory.\nWe train a flow." in text
    assert "draft note" not in text
    assert f"{len(text):,} chars" in result.output
    assert "1,234 tokens" in result.output

    [paper] = rows(installed, "SELECT * FROM papers")
    assert paper["arxiv_id"] == "1904.12072"
    assert paper["latest_version"] == 3
    assert paper["title"].startswith("Flow-based generative models")
    assert paper["authors"] == "M. S. Albergo, G. Kanwar, P. E. Shanahan"
    assert paper["primary_category"] == "hep-lat"
    assert paper["categories"] == "hep-lat cond-mat.dis-nn cond-mat.stat-mech cs.LG"
    assert paper["sets"] == (
        "physics:hep-lat physics:cond-mat:dis-nn physics:cond-mat:stat-mech cs:cs:LG"
    )
    versions = rows(installed, "SELECT * FROM paper_versions ORDER BY version")
    assert [(v["version"], v["submitted_at"]) for v in versions] == [
        (1, "2019-04-26T23:30:09+00:00"),
        (2, "2019-07-31T14:44:25+00:00"),
        (3, "2019-09-09T17:53:37+00:00"),
    ]
    latest = versions[2]
    assert latest["first_seen_datestamp"] == "2019-09-10"
    assert latest["source_type"] == "latex"
    assert latest["sha256"] == hashlib.sha256(SOURCE).hexdigest()
    assert (installed / latest["local_path"]).read_bytes() == SOURCE
    assert latest["fetched_at"]
    assert versions[0]["source_type"] is None


def test_a_second_run_reuses_the_metadata_and_the_download(installed, arxiv, anthropic_api):
    assert phy("read", "--paper", "1904.12072", "--dry-run").exit_code == 0

    result = phy("read", "--paper", "1904.12072", "--dry-run")

    assert result.exit_code == 0, result.output
    assert arxiv.calls.call_count == 2  # one GetRecord and one /src/, both from the first run
    assert (installed / "papers" / "1904.12072v3" / "flattened.txt").is_file()


def test_count_tokens_is_asked_for_the_read_model(installed, arxiv, anthropic_api):
    phy("read", "--paper", "1904.12072", "--dry-run")

    body = json.loads(anthropic_api.calls.last.request.content)
    assert body["model"] == "claude-sonnet-5-5"


def test_single_gzipped_tex_source(installed, anthropic_api):
    with respx.mock() as router:
        router.get(OAI_URL).mock(
            return_value=httpx.Response(
                200, content=(FIXTURES / "getrecord_1904.12072.xml").read_bytes()
            )
        )
        router.get(SRC_URL).mock(
            return_value=httpx.Response(200, content=gzip.compress(b"\\documentclass{x}\nOne.\n"))
        )
        result = phy("read", "--paper", "1904.12072", "--dry-run")

    assert result.exit_code == 0, result.output
    assert "One." in (installed / "papers" / "1904.12072v3" / "flattened.txt").read_text()


def test_pdf_source_is_recorded_as_pdf(installed, anthropic_api, monkeypatch):
    monkeypatch.setattr("phy.read.stage.pdf_text", lambda path: "Page one.\fPage two.")
    with respx.mock() as router:
        router.get(OAI_URL).mock(
            return_value=httpx.Response(
                200, content=(FIXTURES / "getrecord_1904.12072.xml").read_bytes()
            )
        )
        router.get(SRC_URL).mock(return_value=httpx.Response(200, content=b"%PDF-1.4 ..."))
        result = phy("read", "--paper", "1904.12072", "--dry-run")

    assert result.exit_code == 0, result.output
    [latest] = rows(installed, "SELECT * FROM paper_versions WHERE version = 3")
    assert latest["source_type"] == "pdf"
    assert latest["local_path"].endswith(".pdf")
    flattened = installed / "papers" / "1904.12072v3" / "flattened.txt"
    assert flattened.read_text() == "Page one.\fPage two."


def test_unknown_paper_id_fails_cleanly(installed):
    with respx.mock() as router:
        router.get(OAI_URL).mock(
            return_value=httpx.Response(
                200, content=(FIXTURES / "getrecord_iddoesnotexist.xml").read_bytes()
            )
        )
        result = phy("read", "--paper", "9999.99999", "--dry-run")

    assert result.exit_code == 1
    assert "idDoesNotExist" in result.output


def test_malformed_paper_id_is_refused_before_any_request(installed):
    with respx.mock() as router:
        result = phy("read", "--paper", "not-an-id", "--dry-run")

    assert result.exit_code != 0
    assert not router.calls


def test_held_phy_lock_makes_read_exit_zero_without_fetching(installed):
    with respx.mock() as router, phy_lock(resolve_paths()):
        result = phy("read", "--paper", "1904.12072", "--dry-run")

    assert result.exit_code == 0
    assert not router.calls
    assert not (installed / "papers").exists()
