import json
import sqlite3
from importlib.resources import files
from pathlib import Path

import httpx
import pytest
import respx

from phy import llm, prompts
from phy.card import CardDraft
from phy.config import resolve_paths
from phy.ctx import Ctx
from phy.llm import ApiError
from phy.tracer import Run

FIXTURE = Path(__file__).parent / "fixtures" / "anthropic" / "read_1904.12072v3_response.json"
SCHEMAS = Path(__file__).parents[1] / "schemas"
MESSAGES_URL = "https://api.anthropic.com/v1/messages"
PAPER = "\\section{Intro}\nWe train a flow on $\\phi^4$ theory.\n"
AUTHORS = "M. S. Albergo, G. Kanwar, P. E. Shanahan"
RECORDED = json.loads(FIXTURE.read_text())


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
        stage="read",
        arxiv_id="1904.12072",
        model="claude-sonnet-5-5",
        prompt_version="v2",
    )


def runs(ctx):
    conn = sqlite3.connect(ctx.paths.db)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM runs")]
    finally:
        conn.close()


def trace(ctx):
    return [json.loads(line) for line in ctx.paths.run_log(ctx.run_id).open()]


def test_the_read_request_is_laid_out_for_caching(ctx, run):
    with respx.mock(using="httpx2") as router:
        route = router.post(MESSAGES_URL).mock(return_value=httpx.Response(200, json=RECORDED))
        llm.read_card(ctx, run, PAPER, AUTHORS)

    body = json.loads(route.calls.last.request.content)
    assert body["model"] == "claude-sonnet-5-5"
    assert body["system"] == prompts.load("shared", "v1").body
    [turn] = body["messages"]
    paper, instructions = turn["content"]
    assert paper == {
        "type": "text",
        "text": f"<paper>\n{PAPER}\n</paper>",
        "cache_control": {"type": "ephemeral"},
    }
    assert "cache_control" not in instructions
    assert "- Q1. Generative sampling for lattice field theory:" in instructions["text"]
    assert AUTHORS in instructions["text"]
    assert "{{" not in instructions["text"]
    assert body["output_config"]["effort"] == "medium"
    assert body["output_config"]["format"] == {
        "type": "json_schema",
        "schema": json.loads((SCHEMAS / "card_draft.json").read_text()),
    }


def test_a_recorded_response_becomes_a_draft_with_its_cost_traced(ctx, run):
    with respx.mock(using="httpx2") as router:
        router.post(MESSAGES_URL).mock(return_value=httpx.Response(200, json=RECORDED))
        draft = llm.read_card(ctx, run, PAPER, AUTHORS)

    assert isinstance(draft, CardDraft)
    assert draft.tldr.startswith("The authors propose a flow-based MCMC")
    # 1,348 input at $2, 3,074 output at $10 and 25,932 cache-written at $2.50 per million
    hand_cost = (1348 * 2.00 + 3074 * 10.00 + 25932 * 2.50) / 1e6
    [row] = runs(ctx)
    assert row["status"] == "ok"
    assert row["error"] is None
    assert row["stage"] == "read"
    assert row["arxiv_id"] == "1904.12072"
    assert row["model"] == "claude-sonnet-5-5"
    assert row["prompt_version"] == "v2"
    assert (row["tokens_in"], row["tokens_out"]) == (1348, 3074)
    assert (row["cache_write_tokens"], row["cache_read_tokens"]) == (25932, 0)
    assert row["cost_usd"] == pytest.approx(hand_cost)
    assert row["started_at"] <= row["ended_at"]
    assert row["log_path"] == f"runs/{ctx.run_id}.jsonl"

    [line] = trace(ctx)
    assert line["run_id"] == ctx.run_id
    assert line["request"]["messages"][0]["content"][0]["text"] == f"<paper>\n{PAPER}\n</paper>"
    assert line["request"]["output_config"]["format"]["type"] == "json_schema"
    assert line["response"]["id"] == RECORDED["id"]
    assert line["error"] is None
    assert line["cost_usd"] == pytest.approx(hand_cost)


def test_a_cache_read_is_priced_at_the_cache_read_rate(ctx, run):
    usage = {
        **RECORDED["usage"],
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 25932,
    }
    with respx.mock(using="httpx2") as router:
        router.post(MESSAGES_URL).mock(
            return_value=httpx.Response(200, json={**RECORDED, "usage": usage})
        )
        llm.read_card(ctx, run, PAPER, AUTHORS)

    [row] = runs(ctx)
    assert row["cost_usd"] == pytest.approx((1348 * 2.00 + 3074 * 10.00 + 25932 * 0.20) / 1e6)
    assert row["cache_read_tokens"] == 25932


def test_api_errors_leave_a_failed_run(ctx, run):
    with respx.mock(using="httpx2") as router:
        router.post(MESSAGES_URL).mock(
            side_effect=[
                httpx.Response(
                    500, json={"type": "error", "error": {"type": "api_error", "message": "boom"}}
                ),
                httpx.Response(
                    529,
                    json={
                        "type": "error",
                        "error": {"type": "overloaded_error", "message": "Overloaded"},
                    },
                ),
                httpx.Response(
                    529,
                    json={
                        "type": "error",
                        "error": {"type": "overloaded_error", "message": "Overloaded"},
                    },
                ),
            ]
        )
        with pytest.raises(ApiError, match="529"):
            llm.read_card(ctx, run, PAPER, AUTHORS)

    [row] = runs(ctx)
    assert row["status"] == "failed"
    assert "529" in row["error"]
    assert row["cost_usd"] == 0
    [line] = trace(ctx)
    assert line["response"] is None
    assert "529" in line["error"]


def test_a_truncated_response_is_traced_and_fails(ctx, run):
    text = RECORDED["content"][0]["text"][:500]
    truncated = {
        **RECORDED,
        "stop_reason": "max_tokens",
        "content": [{"type": "text", "text": text}],
    }
    with respx.mock(using="httpx2") as router:
        router.post(MESSAGES_URL).mock(return_value=httpx.Response(200, json=truncated))
        with pytest.raises(ApiError, match="max_tokens"):
            llm.read_card(ctx, run, PAPER, AUTHORS)

    [row] = runs(ctx)
    assert row["status"] == "failed"
    assert row["cost_usd"] > 0  # the tokens were paid for
    [line] = trace(ctx)
    assert line["response"]["stop_reason"] == "max_tokens"
