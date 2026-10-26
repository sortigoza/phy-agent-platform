import contextlib
import json
import sqlite3
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from lxml import html

from phy import db, llm
from phy.config import resolve_paths
from phy.ctx import Ctx
from phy.llm import ApiError
from phy.tracer import Run
from phy.ui import app as ui_app

FIXTURE = Path(__file__).parent / "fixtures" / "anthropic" / "read_1904.12072v3_response.json"
RECORDED = json.loads(FIXTURE.read_text())
MESSAGES_URL = "https://api.anthropic.com/v1/messages"
PAPER = "\\section{Intro}\nWe train a flow on $\\phi^4$ theory.\n"


@pytest.fixture
def home(phy_home):
    phy_home.mkdir()
    for name in ["config.toml", "questions.yaml"]:
        (phy_home / name).write_bytes((files("phy") / "defaults" / name).read_bytes())
    db.connect(phy_home / "phy.db").close()
    return phy_home


def add_run(home, run_id, stage, started_at, status="ok", arxiv_id=None, **columns):
    row = {
        "id": run_id,
        "stage": stage,
        "arxiv_id": arxiv_id,
        "status": status,
        "started_at": started_at,
        **columns,
    }
    conn = sqlite3.connect(home / "phy.db")
    with conn:
        conn.execute(
            f"INSERT INTO runs ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
            list(row.values()),
        )
    conn.close()


# Thursday 2026-10-22, 12:00 UTC.
NOW = datetime(2026, 10, 22, 12, tzinfo=UTC).timestamp()


def get(path, status_code=200):
    app = ui_app.create_app(resolve_paths(), clock=lambda: NOW)
    response = TestClient(app).get(path)
    assert response.status_code == status_code, response.text
    if status_code != 200:
        return None
    return html.fromstring(response.text)


def listed(path):
    """The run ids `/runs` lists, top to bottom."""
    return [tr.get("data-run") for tr in get(path).xpath("//tr[@data-run]")]


def text(el):
    return " ".join(el.text_content().split())


def test_runs_are_listed_newest_first_and_filtered_by_stage(home):
    add_run(home, "w1", "watch", "2026-10-20T06:00:00+00:00")
    add_run(home, "r1", "read", "2026-10-21T06:01:00+00:00", arxiv_id="1904.12072")
    add_run(home, "w2", "watch", "2026-10-22T06:00:00+00:00")
    assert listed("/runs") == ["w2", "r1", "w1"]
    assert listed("/runs?stage=watch") == ["w2", "w1"]


def test_runs_are_filtered_by_each_status(home):
    for i, status in enumerate(["ok", "failed", "skipped", "aborted"]):
        add_run(home, status, "read", f"2026-10-2{i}T06:00:00+00:00", status=status)
    for status in ["ok", "failed", "skipped", "aborted"]:
        assert listed(f"/runs?status={status}") == [status]


def test_runs_are_filtered_by_arxiv_ids(home):
    add_run(home, "a", "read", "2026-10-20T06:00:00+00:00", arxiv_id="1904.12072")
    add_run(home, "b", "filter", "2026-10-21T06:00:00+00:00", arxiv_id="2410.01234")
    add_run(home, "c", "read", "2026-10-22T06:00:00+00:00", arxiv_id="2501.00001")
    add_run(home, "watch", "watch", "2026-10-23T06:00:00+00:00")
    assert listed("/runs?ids=1904.12072,2501.00001") == ["c", "a"]
    assert listed("/runs?ids=2410.01234") == ["b"]


def test_runs_are_filtered_by_since(home):
    add_run(home, "last-week", "read", "2026-10-18T23:59:59+00:00")
    add_run(home, "monday", "read", "2026-10-19T00:00:00+00:00")
    add_run(home, "wednesday", "read", "2026-10-21T18:00:00+00:00")
    assert listed("/runs?since=week") == ["wednesday", "monday"]
    assert listed("/runs?since=1d") == ["wednesday"]
    assert listed("/runs?since=7d") == ["wednesday", "monday", "last-week"]
    assert listed("/runs?since=2026-10-19") == ["wednesday", "monday"]
    get("/runs?since=lately", status_code=422)


def test_filters_combine(home):
    add_run(home, "old-fail", "read", "2026-10-01T06:00:00+00:00", "failed", "1904.12072")
    add_run(home, "fail", "read", "2026-10-20T06:00:00+00:00", "failed", "1904.12072")
    add_run(home, "other-paper", "read", "2026-10-20T06:00:00+00:00", "failed", "2501.00001")
    add_run(home, "ok", "read", "2026-10-21T06:00:00+00:00", "ok", "1904.12072")
    add_run(home, "filter-fail", "filter", "2026-10-21T06:00:00+00:00", "failed", "1904.12072")
    query = "/runs?stage=read&status=failed&ids=1904.12072&since=7d"
    assert listed(query) == ["fail"]


def cells(doc, run_id):
    """A listed run's cells, by column heading."""
    headings = [text(th) for th in doc.xpath("//table[@class='runs']//th")]
    [row] = doc.xpath(f"//tr[@data-run='{run_id}']")
    return dict(zip(headings, [text(td) for td in row.xpath("td")], strict=True))


def test_a_run_row_has_the_columns_of_a_model_call(home):
    add_run(
        home,
        "r1",
        "read",
        "2026-10-21T06:00:00+00:00",
        arxiv_id="1904.12072",
        model="claude-sonnet-5-5",
        prompt_version="v2",
        tokens_in=1348,
        tokens_out=3074,
        cache_read_tokens=0,
        cache_write_tokens=25932,
        cost_usd=0.0948,
        ended_at="2026-10-21T06:01:23+00:00",
    )
    doc = get("/runs")
    assert cells(doc, "r1") == {
        "Stage": "read",
        "Paper": "1904.12072",
        "Status": "ok",
        "Model": "claude-sonnet-5-5",
        "Prompt": "v2",
        "Tokens in / out": "27,280 / 3,074",
        "Cost": "$0.0948",
        "Duration": "1:23",
        "Started": "2026-10-21 06:00",
    }
    [link] = doc.xpath("//tr[@data-run='r1']//a[@href='/runs/r1']")
    assert link is not None


def test_status_badges_tell_the_four_statuses_apart(home):
    add_run(home, "w", "watch", "2026-10-21T06:00:00+00:00", ended_at="2026-10-21T06:00:09+00:00")
    for i, status in enumerate(["failed", "skipped", "aborted"]):
        add_run(home, status, "read", f"2026-10-2{i}T06:00:00+00:00", status, "1904.12072")
    doc = get("/runs")
    for status in ["ok", "failed", "skipped", "aborted"]:
        [badge] = doc.xpath(
            f"//span[contains(@class, 'badge') and contains(@class, 'st-{status}')]"
        )
        assert text(badge) == status and badge.get("title")
    assert cells(doc, "w") == {
        "Stage": "watch",
        "Paper": "",
        "Status": "ok",
        "Model": "",
        "Prompt": "",
        "Tokens in / out": "",
        "Cost": "",
        "Duration": "0:09",
        "Started": "2026-10-21 06:00",
    }


def test_the_top_bar_names_the_filter_and_an_empty_list_says_so(home):
    doc = get("/runs?stage=read&status=failed")
    subject = text(doc.xpath("//*[@class='subject']")[0])
    assert "stage=read" in subject and "status=failed" in subject
    assert "No runs match" in text(doc.xpath("//main")[0])
    assert doc.xpath("//nav[@class='pages']/a[@class='on']")[0].text == "runs"


def test_status_pills_switch_status_and_keep_the_other_filters(home):
    doc = get("/runs?stage=read&status=failed&since=7d")
    pills = {text(a): a for a in doc.xpath("//nav[@class='secnav']/a")}
    assert list(pills) == ["all", "ok", "failed", "skipped", "aborted"]
    assert pills["failed"].get("class") == "on"
    assert pills["all"].get("href") == "/runs?stage=read&since=7d"
    assert pills["aborted"].get("href") == "/runs?stage=read&since=7d&status=aborted"


def read(home, monkeypatch, response: httpx.Response) -> str:
    """Make one Read call on PAPER, replayed with `response`, and return its run id."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    ctx = Ctx.load(resolve_paths())
    run = Run(ctx.run_id, "read", "1904.12072", "claude-sonnet-5-5", "v2")
    with respx.mock(using="httpx2") as router:
        router.post(MESSAGES_URL).mock(return_value=response)
        with contextlib.suppress(ApiError):
            llm.read_card(ctx, run, PAPER, "Albergo, Kanwar, Shanahan")
    return ctx.run_id


def section(doc, name):
    [el] = doc.xpath(f"//section[@data-section='{name}']")
    return el


def test_the_viewer_shows_a_read_call_with_the_paper_text_collapsed(home, monkeypatch):
    run_id = read(home, monkeypatch, httpx.Response(200, json=RECORDED))
    doc = get(f"/runs/{run_id}")

    subject = text(doc.xpath("//*[@class='subject']")[0])
    assert "read" in subject and "1904.12072" in subject
    request = section(doc, "request")
    assert "claude-sonnet-5-5" in text(request) and "v2" in text(request)
    [paper] = request.xpath(".//details[@class='paper']")
    assert "open" not in paper.attrib
    assert "We train a flow on $\\phi^4$ theory." in paper.text_content()
    assert "characters" in text(paper.xpath("summary")[0])
    assert "Albergo, Kanwar, Shanahan" in text(request)  # the instructions are not folded
    assert "end_turn" in text(section(doc, "response"))
    output = text(section(doc, "output"))
    assert "The authors propose a flow-based MCMC" in output
    assert "No validation errors" in text(section(doc, "errors"))
    usage = text(section(doc, "usage"))
    # 1,348 uncached input at $2, 3,074 output at $10 and 25,932 cache-written at $2.50 per M
    assert "$0.0983" in usage
    assert "1,348" in usage and "3,074" in usage and "25,932" in usage
    assert "cache reads 0" in usage


def test_the_viewer_shows_why_a_truncated_call_failed(home, monkeypatch):
    truncated = {
        **RECORDED,
        "stop_reason": "max_tokens",
        "content": [{"type": "text", "text": RECORDED["content"][0]["text"][:500]}],
    }
    run_id = read(home, monkeypatch, httpx.Response(200, json=truncated))
    doc = get(f"/runs/{run_id}")
    assert doc.xpath("//span[contains(@class, 'st-failed')]")
    assert "stopped with max_tokens" in text(section(doc, "errors"))
    assert "not valid JSON" in text(section(doc, "output"))
    assert "$0.0" in text(section(doc, "usage"))  # the tokens were paid for


def test_the_viewer_shows_an_api_error_with_no_response(home, monkeypatch):
    error = {"type": "error", "error": {"type": "invalid_request_error", "message": "bad"}}
    run_id = read(home, monkeypatch, httpx.Response(400, json=error))
    doc = get(f"/runs/{run_id}")
    assert "HTTP 400" in text(section(doc, "errors"))
    assert "No response" in text(section(doc, "response"))


def test_a_missing_log_file_is_said_not_raised(home):
    add_run(
        home,
        "gone",
        "read",
        "2026-10-21T06:00:00+00:00",
        "ok",
        "1904.12072",
        log_path="runs/gone.jsonl",
    )
    doc = get("/runs/gone")
    assert "log file runs/gone.jsonl is missing" in text(doc.xpath("//main")[0])


@pytest.mark.parametrize(
    ("status", "error"),
    [("skipped", "too_long: 201234 tokens"), ("aborted", "credit balance too low")],
)
def test_a_run_without_a_model_call_shows_its_error_line_only(home, status, error):
    add_run(home, status, "read", "2026-10-21T06:00:00+00:00", status, "1904.12072", error=error)
    doc = get(f"/runs/{status}")
    main = doc.xpath("//main")[0]
    assert doc.xpath(f"//span[contains(@class, 'st-{status}')]")
    assert error in text(main)
    assert not main.xpath(".//section[@data-section]")
    assert "missing" not in text(main)


def test_an_unknown_run_is_not_found(home):
    get("/runs/nope", status_code=404)


def test_the_viewer_lists_each_validation_error(home, monkeypatch):
    invalid = {**RECORDED, "content": [{"type": "text", "text": '{"tldr": 7}'}]}
    run_id = read(home, monkeypatch, httpx.Response(200, json=invalid))
    errors = text(section(get(f"/runs/{run_id}"), "errors"))
    assert "fails its schema" in errors
    assert "tldr: Input should be a valid string" in errors
    assert "key_results: Field required" in errors


def test_an_unreadable_log_line_is_said_not_raised(home, monkeypatch):
    run_id = read(home, monkeypatch, httpx.Response(200, json=RECORDED))
    with resolve_paths().run_log(run_id).open("a") as f:
        f.write('{"run_id": "cut off')
    doc = get(f"/runs/{run_id}")
    assert "1 log line could not be read" in text(doc.xpath("//main")[0])
    assert len(doc.xpath("//section[@data-section='request']")) == 1
