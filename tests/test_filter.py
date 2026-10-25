import json
import sqlite3
from datetime import UTC, date, datetime
from importlib.resources import files
from pathlib import Path

import httpx
import pytest
import respx
import yaml
from typer.testing import CliRunner

from phy import db
from phy.arxiv import ArxivRecord, Version
from phy.cli import app
from phy.config import Questions, resolve_paths
from phy.filter import prefilter
from phy.locks import phy_lock

DEFAULT = Questions.model_validate(
    yaml.safe_load((files("phy") / "defaults" / "questions.yaml").read_text())
)
MODES = {
    "physics:hep-lat": "none",
    "physics:quant-ph": "keywords",
    "cs:cs:LG": "keywords+physics",
}

FLOW = "A normalizing flow sampler"
FLOW_LATTICE = "A normalizing flow sampler for lattice field theory"
NO_KEYWORD = "Muon g-2 from lattice QCD"
HARDWARE = "Normalizing flow calibration of quantum hardware"
PER_QUESTION_NEGATIVE = Questions.model_validate(
    {
        **DEFAULT.model_dump(),
        "questions": [
            {**DEFAULT.questions[0].model_dump(), "negative_keywords": ["image generation"]},
            *[q.model_dump() for q in DEFAULT.questions[1:]],
        ],
    }
)


@pytest.mark.parametrize(
    ("title", "sets", "expected"),
    [
        (NO_KEYWORD, ["physics:hep-lat"], "skipped"),
        (FLOW, ["physics:quant-ph"], "pass"),
        (NO_KEYWORD, ["physics:quant-ph"], "fail"),
        (HARDWARE, ["physics:quant-ph"], "fail"),  # a global negative keyword
        (FLOW, ["cs:cs:LG"], "fail"),  # no physics term
        (FLOW_LATTICE, ["cs:cs:LG"], "pass"),
        (NO_KEYWORD, ["cs:cs:LG"], "fail"),  # a physics term but no question keyword
        # cross-listed: the most permissive of its sets wins
        (FLOW, ["cs:cs:LG", "physics:quant-ph"], "pass"),
        (NO_KEYWORD, ["cs:cs:LG", "physics:hep-lat"], "skipped"),
        # a set no longer configured is ignored; with none left, the strictest mode applies
        (FLOW, ["physics:gone", "physics:quant-ph"], "pass"),
        (FLOW, ["physics:gone"], "fail"),
    ],
)
def test_prefilter(title, sets, expected):
    assert prefilter(title, "", sets, MODES, DEFAULT) == expected


def test_keywords_match_in_the_abstract_case_and_line_breaks_ignored():
    abstract = "We train a Normalizing\n  Flow on phi^4 theory."
    assert prefilter("Untitled", abstract, ["physics:quant-ph"], MODES, DEFAULT) == "pass"


def test_keywords_match_at_word_starts_only():
    # "spin" is a physics term; "transpinal" must not count as one
    title = "A normalizing flow for transpinal imaging"
    assert prefilter(title, "", ["cs:cs:LG"], MODES, DEFAULT) == "fail"
    assert prefilter(title + " of spins", "", ["cs:cs:LG"], MODES, DEFAULT) == "pass"


def test_a_question_negative_keyword_vetoes_only_that_question():
    title = "Normalizing flow for image generation"
    assert prefilter(title, "", ["physics:quant-ph"], MODES, PER_QUESTION_NEGATIVE) == "fail"
    title += " with a variational wavefunction"  # Q2 still matches
    assert prefilter(title, "", ["physics:quant-ph"], MODES, PER_QUESTION_NEGATIVE) == "pass"


# The Stage, through `phy filter`, with the Filter calls replayed.

FILTER_RESPONSE = json.loads(
    (
        Path(__file__).parent / "fixtures" / "anthropic" / "filter_1904.12072_response.json"
    ).read_text()
)
MESSAGES_URL = "https://api.anthropic.com/v1/messages"
OVERLOADED = httpx.Response(
    529, json={"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}
)


def record(arxiv_id, title, sets, categories, versions=1):
    return ArxivRecord(
        arxiv_id=arxiv_id,
        datestamp=date(2026, 10, 23),
        sets=sets,
        title=title,
        authors="A. Author",
        abstract="An abstract.",
        categories=categories,
        license=None,
        versions=[
            Version(number=n, submitted_at=datetime(2026, 10, 20 + n, tzinfo=UTC))
            for n in range(1, versions + 1)
        ],
    )


HEP_LAT = record("2610.00001", NO_KEYWORD, ["physics:hep-lat"], ["hep-lat"], versions=2)
QUANT_PH = record("2610.00002", FLOW, ["physics:quant-ph"], ["quant-ph"])
CS_LG = record("2610.00003", FLOW, ["cs:cs:LG"], ["cs.LG"])


@pytest.fixture
def installed(phy_home, monkeypatch):
    phy_home.mkdir()
    for name in ["config.toml", "questions.yaml"]:
        (phy_home / name).write_bytes((files("phy") / "defaults" / name).read_bytes())
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr("anthropic._base_client.time.sleep", lambda _: None)
    conn = db.connect(phy_home / "phy.db")
    for r in [HEP_LAT, QUANT_PH, CS_LG]:
        db.upsert_paper(conn, r)
    conn.close()
    return phy_home


@pytest.fixture
def messages_api():
    with respx.mock(using="httpx2", assert_all_called=False) as router:
        yield router.post(MESSAGES_URL).mock(return_value=httpx.Response(200, json=FILTER_RESPONSE))


def phy(*args):
    return CliRunner().invoke(app, ["filter", *args])


def rows(phy_home, sql):
    conn = sqlite3.connect(phy_home / "phy.db")
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql)]
    finally:
        conn.close()


def screenings(phy_home):
    return {(r["arxiv_id"], r["version"]): r for r in rows(phy_home, "SELECT * FROM screenings")}


def test_filter_screens_the_latest_version_of_every_paper(installed, messages_api):
    result = phy()

    assert result.exit_code == 0, result.output
    assert messages_api.call_count == 2  # hep-lat skips the pre-filter; quant-ph passes it
    found = screenings(installed)
    assert set(found) == {("2610.00001", 2), ("2610.00002", 1), ("2610.00003", 1)}

    candidate = found[("2610.00001", 2)]
    assert candidate["prefilter"] == "skipped"
    assert json.loads(candidate["scores_json"])["Q1"]["score"] == 0.95
    assert candidate["best_score"] == 0.95
    assert candidate["screened_in"] == 1
    assert (candidate["model"], candidate["prompt_version"]) == ("claude-haiku-5-5", "v1")
    assert found[("2610.00002", 1)]["prefilter"] == "pass"

    failed = found[("2610.00003", 1)]
    assert failed["prefilter"] == "fail"
    assert failed["scores_json"] is None
    assert failed["best_score"] is None
    assert failed["screened_in"] == 0
    assert failed["model"] is None

    # one runs row per call, and one for the Stage run that pre-filter fails point at
    runs = {r["id"]: r for r in rows(installed, "SELECT * FROM runs")}
    call = runs[candidate["run_id"]]
    assert (call["stage"], call["arxiv_id"], call["status"]) == ("filter", "2610.00001", "ok")
    assert call["cost_usd"] > 0
    stage = runs[failed["run_id"]]
    assert (stage["stage"], stage["arxiv_id"], stage["status"]) == ("filter", None, "ok")
    assert len(runs) == 3
    assert "2 candidates, 2 screened in, 1 pre-filter fail" in result.output


def test_a_score_below_the_threshold_is_not_screened_in(installed, monkeypatch):
    output = {q: {"reason": "Shared words only.", "score": 0.3} for q in ["Q1", "Q2", "Q3", "Q4"]}
    body = {**FILTER_RESPONSE, "content": [{"type": "text", "text": json.dumps(output)}]}
    with respx.mock(using="httpx2") as router:
        router.post(MESSAGES_URL).mock(return_value=httpx.Response(200, json=body))
        assert phy().exit_code == 0

    found = screenings(installed)[("2610.00001", 2)]
    assert (found["best_score"], found["screened_in"]) == (0.3, 0)


def test_a_second_run_screens_nothing_new(installed, messages_api):
    assert phy().exit_code == 0
    before = screenings(installed)

    result = phy()

    assert result.exit_code == 0, result.output
    assert messages_api.call_count == 2  # both from the first run
    assert screenings(installed) == before


def test_a_new_version_is_screened_on_the_next_run(installed, messages_api):
    assert phy().exit_code == 0
    conn = db.connect(installed / "phy.db")
    db.upsert_paper(conn, record("2610.00002", FLOW, ["physics:quant-ph"], ["quant-ph"], 2))
    conn.close()

    assert phy().exit_code == 0

    assert messages_api.call_count == 3
    assert ("2610.00002", 2) in screenings(installed)


def test_paper_with_force_redoes_one_screening(installed, messages_api):
    assert phy().exit_code == 0
    old = screenings(installed)[("2610.00002", 1)]

    assert phy("--paper", "2610.00002").exit_code == 0
    assert messages_api.call_count == 2  # already screened: left alone without --force

    result = phy("--paper", "2610.00002", "--force")

    assert result.exit_code == 0, result.output
    assert messages_api.call_count == 3
    new = screenings(installed)
    assert new[("2610.00002", 1)]["run_id"] != old["run_id"]
    assert len(new) == 3


def test_paper_screens_only_that_paper(installed, messages_api):
    result = phy("--paper", "2610.00003")

    assert result.exit_code == 0, result.output
    assert messages_api.call_count == 0
    assert set(screenings(installed)) == {("2610.00003", 1)}


def test_force_needs_paper(installed, messages_api):
    result = phy("--force")

    assert result.exit_code != 0
    assert not messages_api.called


def test_an_unknown_paper_fails_cleanly(installed, messages_api):
    result = phy("--paper", "9999.99999")

    assert result.exit_code == 1
    assert "9999.99999" in result.output


def test_a_failed_call_leaves_that_paper_unscreened_for_the_next_run(installed):
    with respx.mock(using="httpx2") as router:
        route = router.post(MESSAGES_URL).mock(
            side_effect=[
                OVERLOADED,
                OVERLOADED,
                OVERLOADED,
                httpx.Response(200, json=FILTER_RESPONSE),
            ]
        )
        result = phy()

        assert result.exit_code == 1
        assert route.call_count == 4  # three tries for the first Candidate, one for the second
        assert ("2610.00001", 2) not in screenings(installed)
        assert ("2610.00002", 1) in screenings(installed)
        [failed] = rows(installed, "SELECT * FROM runs WHERE status = 'failed'")
        assert failed["arxiv_id"] == "2610.00001"

        route.side_effect = None
        route.return_value = httpx.Response(200, json=FILTER_RESPONSE)
        assert phy().exit_code == 0

    assert ("2610.00001", 2) in screenings(installed)


def test_held_phy_lock_makes_filter_exit_zero_without_calls(installed, messages_api):
    with phy_lock(resolve_paths()):
        result = phy()

    assert result.exit_code == 0
    assert not messages_api.called
    assert screenings(installed) == {}
