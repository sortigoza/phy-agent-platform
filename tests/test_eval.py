"""`phy eval` on two synthetic Golden entries, with replayed Read and Filter responses.

Hand-computed Scores: 2101.00001 has 4 quotes with 3 found, no invented number, and is
screened in as expected. 2101.00002 has 4 quotes all found, one invented number (42) and is
screened in though the manifest expects it out of scope. Overall: 7 of 8 quotes found, 1
invented number (a hard fail), 1 of 2 Filter decisions correct.
"""

import hashlib
import json
import sqlite3
from datetime import UTC, date, datetime
from importlib.resources import files

import httpx
import pytest
import respx
from typer.testing import CliRunner

from phy import db, golden
from phy.arxiv import ArxivRecord, Version
from phy.cli import app
from phy.config import resolve_paths

MESSAGES_URL = "https://api.anthropic.com/v1/messages"

A_SOURCE = r"""\documentclass{article}
\begin{document}
\section{Introduction}
We train a normalizing flow to sample lattice configurations directly from the target
distribution.

\section{Method}
The flow is composed of affine coupling layers acting on checkerboard partitions of the
lattice.

\section{Results}
The integrated autocorrelation time stays flat as the correlation length grows in our runs.
\end{document}
"""

B_SOURCE = r"""\documentclass{article}
\begin{document}
\section{Model}
We study the transverse field Ising chain with a neural network wavefunction ansatz.

\section{Results}
The variational energy matches exact diagonalisation within statistical error bars.
\end{document}
"""


def fact(quote: str, value: str) -> dict:
    return {"evidence": [{"quote": quote}], "value": value, "inferred": False}


def draft(result: dict, system: dict, method: dict, advance: dict) -> dict:
    return {
        "tldr": "A synthetic Card for the eval tests.",
        "key_results": [result],
        "assumptions": [],
        "system": system,
        "method": method,
        "baselines": None,
        "claimed_advance": advance,
        "limitations_stated": [],
        "key_equations": [],
        "key_figures": [],
        "code_data": None,
        "questions": [],
        "opinion": {"limitations_flagged": [], "deep_read": {"recommend": False, "why": "x"}},
    }


A_DRAFT = draft(
    fact(
        "The integrated autocorrelation time stays flat as the correlation length grows",
        "No critical slowing down",
    ),
    fact("sample lattice configurations directly from the target distribution", "Lattice"),
    fact("composed of affine coupling layers acting on checkerboard partitions", "Flow"),
    fact("the sampler removes critical slowing down entirely at no cost", "Free lunch"),
)
B_DRAFT = draft(
    fact(
        "The variational energy matches exact diagonalisation within statistical error bars",
        "Energy within 42 percent",
    ),
    fact("the transverse field Ising chain with a neural network wavefunction ansatz", "Ising"),
    fact("We study the transverse field Ising chain", "Ising chain"),
    fact("matches exact diagonalisation within statistical error bars", "Matches ED"),
)


def scores(**best: float) -> dict:
    return {q: {"reason": "r", "score": best.get(q, 0.0)} for q in ["Q1", "Q2", "Q3", "Q4"]}


PAPERS = {
    "2101.00001": {
        "title": "Flows for lattice sampling",
        "source": A_SOURCE,
        "marker": "affine coupling layers",
        "draft": A_DRAFT,
        "scores": scores(Q1=0.9),
        "expect_in_scope": True,
    },
    "2101.00002": {
        "title": "Neural states for the Ising chain",
        "source": B_SOURCE,
        "marker": "transverse field Ising chain",
        "draft": B_DRAFT,
        "scores": scores(Q2=0.8),
        "expect_in_scope": False,
    },
}


def message(model: str, output: dict) -> dict:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": json.dumps(output)}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 1000, "output_tokens": 100},
    }


def respond(request: httpx.Request) -> httpx.Response:
    """The Filter response for a Paper's title, or the Read response for its source."""
    body = json.loads(request.content)
    sent = json.dumps(body["messages"])
    for paper in PAPERS.values():
        if body["model"] == "claude-haiku-5-5" and paper["title"] in sent:
            return httpx.Response(200, json=message(body["model"], paper["scores"]))
        if body["model"] != "claude-haiku-5-5" and paper["marker"] in sent:
            return httpx.Response(200, json=message(body["model"], paper["draft"]))
    raise AssertionError(f"no replayed response for {sent[:200]}")


@pytest.fixture
def golden_set(phy_home, monkeypatch):
    """Two Dev Placeholders with frozen sources, and their Papers in the database."""
    (phy_home / "golden").mkdir(parents=True)
    for name in ["config.toml", "questions.yaml"]:
        (phy_home / name).write_bytes((files("phy") / "defaults" / name).read_bytes())
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    paths = resolve_paths()
    conn = db.connect(paths.db)
    entries = []
    for arxiv_id, paper in PAPERS.items():
        db.upsert_paper(
            conn,
            ArxivRecord(
                arxiv_id=arxiv_id,
                datestamp=date(2026, 10, 1),
                sets=["physics:hep-lat"],
                title=paper["title"],
                authors="A. Author",
                abstract="An abstract.",
                categories=["hep-lat"],
                license=None,
                versions=[Version(1, datetime(2026, 1, 1, tzinfo=UTC))],
            ),
        )
        paths.golden_source(arxiv_id, 1).mkdir(parents=True)
        source = paths.golden_source_file(arxiv_id, 1, "tar.gz")
        source.write_bytes(paper["source"].encode())
        paths.golden_flattened(arxiv_id, 1).write_text(paper["source"])
        entries.append(
            golden.Entry(
                arxiv_id=arxiv_id,
                version=1,
                sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                split="dev",
                status="placeholder",
                reason="seed",
                expect_in_scope=paper["expect_in_scope"],
                added_at=date(2026, 10, 26),
                corrected_by=None,
                corrected_at=None,
            )
        )
    conn.close()
    golden.save(paths, golden.Manifest(version=3, papers=entries))
    return phy_home


@pytest.fixture
def messages_api(monkeypatch):
    monkeypatch.setattr("anthropic._base_client.time.sleep", lambda _: None)
    with respx.mock(using="httpx2", assert_all_called=False) as router:
        yield router.post(MESSAGES_URL).mock(side_effect=respond)


def phy(*args):
    return CliRunner().invoke(app, list(args))


def rows(phy_home, sql):
    conn = sqlite3.connect(phy_home / "phy.db")
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql)]
    finally:
        conn.close()


def test_scores_match_the_hand_computed_values(golden_set, messages_api):
    result = phy("eval")

    assert result.exit_code == 1, result.output  # the invented number is a hard fail
    [run] = rows(golden_set, "SELECT * FROM eval_runs")
    assert (run["golden_version"], run["split"]) == (3, "dev")
    metrics = json.loads(run["metrics_json"])
    assert metrics["grounding_rate"] == pytest.approx(7 / 8)
    assert (metrics["quotes"], metrics["quotes_found"]) == (8, 7)
    assert metrics["invented_numbers"] == 1
    assert (metrics["filter_correct"], metrics["filter_total"]) == (1, 2)

    a, b = json.loads(run["per_paper_json"])
    assert (a["arxiv_id"], a["version"]) == ("2101.00001", 1)
    assert a["grounding_rate"] == pytest.approx(3 / 4)
    assert a["invented_numbers"] == []
    assert a["filter"]["screened_in"] is True and a["filter"]["correct"] is True
    assert b["grounding_rate"] == 1.0
    assert b["invented_numbers"] == [{"field": "key_results[0]", "number": "42"}]
    assert b["filter"]["screened_in"] is True and b["filter"]["correct"] is False
    assert b["card"]["key_results"][0]["support"] == "unsupported"

    assert messages_api.call_count == 4
    assert rows(golden_set, "SELECT * FROM cards") == []
    assert run["id"] in result.output
    assert "2101.00001v1" in result.output and "2101.00002v1" in result.output
    assert "87.5%" in result.output and "hard fail" in result.output


def read_requests(router) -> list[str]:
    return [
        json.dumps(json.loads(call.request.content)["messages"])
        for call in router.calls
        if json.loads(call.request.content)["model"] != "claude-haiku-5-5"
    ]


def test_the_active_prompts_are_recorded(golden_set, messages_api):
    phy("eval")

    [run] = rows(golden_set, "SELECT * FROM eval_runs")
    assert json.loads(run["prompt_versions_json"]) == {"read": "v2", "filter": "v1"}
    assert run["model"] == "claude-sonnet-5-5"
    assert all("## Wording" in sent for sent in read_requests(messages_api))


def test_a_prompt_override_is_loaded_and_recorded(golden_set, messages_api):
    phy("eval", "--prompt", "read=v1", "--prompt", "filter=v1")

    [run] = rows(golden_set, "SELECT * FROM eval_runs")
    assert json.loads(run["prompt_versions_json"]) == {"read": "v1", "filter": "v1"}
    sent = read_requests(messages_api)
    assert len(sent) == 2 and not any("## Wording" in s for s in sent)
    reads = rows(golden_set, "SELECT prompt_version FROM runs WHERE id LIKE '%-read'")
    assert [r["prompt_version"] for r in reads] == ["v1", "v1"]


def test_an_unknown_prompt_version_fails_before_any_call(golden_set, messages_api):
    result = phy("eval", "--prompt", "read=v9")

    assert result.exit_code == 1
    assert messages_api.call_count == 0
    assert rows(golden_set, "SELECT * FROM eval_runs") == []


def test_an_override_of_another_stage_is_rejected(golden_set, messages_api):
    result = phy("eval", "--prompt", "verify=v1")

    assert result.exit_code == 2
    assert messages_api.call_count == 0


def test_a_sha256_mismatch_aborts_with_no_calls(golden_set, messages_api):
    (golden_set / "golden_sources" / "2101.00002v1" / "source.tar.gz").write_bytes(b"edited")

    result = phy("eval")

    assert result.exit_code == 1
    assert messages_api.call_count == 0
    assert rows(golden_set, "SELECT * FROM eval_runs") == []
    [run] = rows(golden_set, "SELECT * FROM runs")
    assert (run["stage"], run["status"]) == ("eval", "failed")
    assert "2101.00002v1: source.tar.gz sha256" in run["error"]


def test_an_empty_manifest_aborts_with_no_calls(golden_set, messages_api):
    golden.save(resolve_paths(), golden.Manifest(version=0, papers=[]))

    result = phy("eval")

    assert result.exit_code == 1
    assert messages_api.call_count == 0
    assert "no dev Papers" in rows(golden_set, "SELECT error FROM runs")[0]["error"]


def test_eval_spend_is_traced_in_runs(golden_set, messages_api):
    phy("eval")

    calls = rows(golden_set, "SELECT * FROM runs WHERE id != (SELECT id FROM eval_runs)")
    assert len(calls) == 4
    assert {(c["stage"], c["status"]) for c in calls} == {("eval", "ok")}
    assert all(c["cost_usd"] > 0 for c in calls)
    assert all((golden_set / c["log_path"]).is_file() for c in calls)
    models = sorted(c["model"] for c in calls)
    assert models == ["claude-haiku-5-5"] * 2 + ["claude-sonnet-5-5"] * 2


def test_a_failed_call_fails_the_eval_and_stores_no_scores(golden_set, messages_api):
    messages_api.side_effect = None
    messages_api.return_value = httpx.Response(500, json={"type": "error"})

    result = phy("eval")

    assert result.exit_code == 1
    assert rows(golden_set, "SELECT * FROM eval_runs") == []
    statuses = {r["status"] for r in rows(golden_set, "SELECT status FROM runs")}
    assert statuses == {"failed"}


def test_a_prefilter_fail_is_screened_out_without_a_filter_call(golden_set, messages_api):
    conn = sqlite3.connect(golden_set / "phy.db")
    with conn:  # cs:cs:LG is keywords+physics, and B's abstract has no keyword
        conn.execute("UPDATE papers SET sets = 'cs:cs:LG' WHERE arxiv_id = '2101.00002'")
    conn.close()

    phy("eval")

    [run] = rows(golden_set, "SELECT * FROM eval_runs")
    _, b = json.loads(run["per_paper_json"])
    assert b["filter"]["prefilter"] == "fail"
    assert (b["filter"]["screened_in"], b["filter"]["correct"]) == (False, True)
    assert json.loads(run["metrics_json"])["filter_correct"] == 2
    assert messages_api.call_count == 3
