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
MESSAGES_URL = "https://api.anthropic.com/v1/messages"
RECORDED = json.loads(
    (
        Path(__file__).parent / "fixtures" / "anthropic" / "read_1904.12072v3_response.json"
    ).read_text()
)
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


@pytest.fixture
def messages_api(monkeypatch):
    monkeypatch.setattr("anthropic._base_client.time.sleep", lambda _: None)
    with respx.mock(using="httpx2") as router:
        yield router.post(MESSAGES_URL).mock(return_value=httpx.Response(200, json=RECORDED))


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


def test_read_writes_a_draft_card_from_one_traced_call(installed, arxiv, messages_api):
    result = phy("read", "--paper", "1904.12072")

    assert result.exit_code == 0, result.output
    assert messages_api.call_count == 1
    body = json.loads(messages_api.calls.last.request.content)
    assert "M. S. Albergo, G. Kanwar, P. E. Shanahan" in body["messages"][0]["content"][1]["text"]
    assert "Lattice field theory." in body["messages"][0]["content"][0]["text"]

    [card] = rows(installed, "SELECT * FROM cards")
    assert (card["arxiv_id"], card["version"], card["status"]) == ("1904.12072", 3, "draft")
    assert card["model"] == "claude-sonnet-5-5"
    assert card["prompt_version"] == "v2"
    assert card["schema_version"] == "card/v1"
    assert json.loads(card["card_json"])["tldr"].startswith("The authors propose")
    [run] = rows(installed, "SELECT * FROM runs")
    assert run["id"] == card["run_id"]
    assert (run["stage"], run["status"], run["arxiv_id"]) == ("read", "ok", "1904.12072")
    assert (installed / run["log_path"]).is_file()
    assert f"card {card['id']}" in result.output
    assert "$0.0983" in result.output


def test_a_second_read_replaces_nothing(installed, arxiv, messages_api):
    assert phy("read", "--paper", "1904.12072").exit_code == 0
    [before] = rows(installed, "SELECT * FROM cards")

    result = phy("read", "--paper", "1904.12072")

    assert result.exit_code == 0, result.output
    assert messages_api.call_count == 1
    assert rows(installed, "SELECT * FROM cards") == [before]
    assert "--force" in result.output


def test_force_replaces_the_card_in_place(installed, arxiv, messages_api):
    assert phy("read", "--paper", "1904.12072").exit_code == 0
    [before] = rows(installed, "SELECT * FROM cards")

    result = phy("read", "--paper", "1904.12072", "--force")

    assert result.exit_code == 0, result.output
    assert messages_api.call_count == 2
    [after] = rows(installed, "SELECT * FROM cards")
    assert after["id"] == before["id"]
    assert after["run_id"] != before["run_id"]
    assert len(rows(installed, "SELECT * FROM runs")) == 2


def test_a_failed_call_leaves_a_failed_run_and_no_card(installed, arxiv, messages_api):
    overloaded = {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}
    messages_api.mock(
        side_effect=[
            httpx.Response(
                500, json={"type": "error", "error": {"type": "api_error", "message": "boom"}}
            ),
            httpx.Response(529, json=overloaded),
            httpx.Response(529, json=overloaded),
        ]
    )

    result = phy("read", "--paper", "1904.12072")

    assert result.exit_code == 1
    assert "529" in result.output
    assert rows(installed, "SELECT * FROM cards") == []
    [run] = rows(installed, "SELECT * FROM runs")
    assert run["status"] == "failed"
    assert "529" in run["error"]


def test_schema_export_writes_both_schemas(tmp_path):
    result = phy("schema", "export", "--dir", str(tmp_path))

    assert result.exit_code == 0, result.output
    assert sorted(p.name for p in tmp_path.iterdir()) == ["card.json", "card_draft.json"]
