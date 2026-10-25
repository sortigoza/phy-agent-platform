"""The Filter call. The fixture is the first 1904.12072 call of the Filter prompt prototype
(`out/v1a.jsonl`, request req_011CgNwwPjwQG9xFFSgV8Dnw) put back into a Messages response."""

import json
import sqlite3
from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path

import httpx
import pytest
import respx
from structlog.testing import capture_logs

from phy import llm, prompts
from phy.config import resolve_paths
from phy.ctx import Ctx
from phy.questions import render_questions, render_scope_notes
from phy.screening import scores_format
from phy.tracer import Run

FIXTURE = Path(__file__).parent / "fixtures" / "anthropic" / "filter_1904.12072_response.json"
MESSAGES_URL = "https://api.anthropic.com/v1/messages"
RECORDED = json.loads(FIXTURE.read_text())
TITLE = "Flow-based generative models for Markov chain Monte Carlo in lattice field theory"
CATEGORIES = "hep-lat cond-mat.stat-mech cs.LG"
ABSTRACT = "A Markov chain update scheme using a machine-learned flow-based generative model."


@pytest.fixture
def ctx(phy_home, monkeypatch):
    phy_home.mkdir()
    for name in ["config.toml", "questions.yaml"]:
        (phy_home / name).write_bytes((files("phy") / "defaults" / name).read_bytes())
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr("anthropic._base_client.time.sleep", lambda _: None)
    return Ctx.load(resolve_paths())


@pytest.fixture
def run(ctx):
    return Run(
        id=ctx.run_id,
        stage="filter",
        arxiv_id="1904.12072",
        model="claude-haiku-5-5",
        prompt_version="v1",
    )


def runs(ctx):
    conn = sqlite3.connect(ctx.paths.db)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM runs")]
    finally:
        conn.close()


@contextmanager
def respond(body):
    with respx.mock(using="httpx2") as router:
        yield router.post(MESSAGES_URL).mock(return_value=httpx.Response(200, json=body))


def test_the_filter_request_caches_the_system_prompt(ctx, run):
    with respond(RECORDED) as route:
        llm.screen(ctx, run, TITLE, CATEGORIES, ABSTRACT)

    body = json.loads(route.calls.last.request.content)
    assert body["model"] == "claude-haiku-5-5"
    system = prompts.load("filter", "v1").render(
        questions=render_questions(ctx.questions), scope_notes=render_scope_notes(ctx.questions)
    )
    assert body["system"] == [
        {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
    ]
    assert "- Q1. Generative sampling for lattice field theory:" in system
    assert "- Quantum-computing hardware" in system
    assert body["messages"] == [
        {
            "role": "user",
            "content": f"<paper>\nTitle: {TITLE}\nCategories: hep-lat, cond-mat.stat-mech,"
            f" cs.LG\n\nAbstract: {ABSTRACT}\n</paper>",
        }
    ]
    assert body["output_config"] == {"effort": "low", "format": scores_format(ctx.questions)}


def test_a_recorded_response_becomes_scores_with_its_cost_traced(ctx, run):
    with respond(RECORDED):
        scores = llm.screen(ctx, run, TITLE, CATEGORIES, ABSTRACT)

    assert {qid: s["score"] for qid, s in scores.items()} == {
        "Q1": 0.95,
        "Q2": 0.05,
        "Q3": 0.2,
        "Q4": 0.05,
    }
    assert scores["Q1"]["reason"].startswith("Flow-based generative model as MCMC update")
    [row] = runs(ctx)
    assert (row["stage"], row["status"], row["arxiv_id"]) == ("filter", "ok", "1904.12072")
    assert (row["model"], row["prompt_version"]) == ("claude-haiku-5-5", "v1")
    assert (row["tokens_in"], row["tokens_out"], row["cache_write_tokens"]) == (330, 216, 1347)
    # the prototype measured this call at $0.000309375
    assert row["cost_usd"] == pytest.approx(0.000309375)


def test_a_score_out_of_range_is_clamped_with_a_warning(ctx, run):
    output = json.loads(RECORDED["content"][0]["text"])
    output["Q1"]["score"] = 1.2
    output["Q2"]["score"] = -0.1
    body = {**RECORDED, "content": [{"type": "text", "text": json.dumps(output)}]}
    with respond(body), capture_logs() as logs:
        scores = llm.screen(ctx, run, TITLE, CATEGORIES, ABSTRACT)

    assert (scores["Q1"]["score"], scores["Q2"]["score"]) == (1.0, 0.0)
    clamped = [e for e in logs if e["event"] == "llm.score_clamped"]
    assert [(e["question"], e["score"], e["log_level"]) for e in clamped] == [
        ("Q1", 1.2, "warning"),
        ("Q2", -0.1, "warning"),
    ]
