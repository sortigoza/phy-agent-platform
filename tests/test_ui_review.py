import io
import json
import sqlite3
from importlib.resources import files

import pytest
from cards import RECORDED_DRAFT, SEED_LIKE
from fastapi.testclient import TestClient
from lxml import html
from PIL import Image
from typer.testing import CliRunner

from phy import db
from phy.cli import app as cli
from phy.config import resolve_paths
from phy.release import ReleaseStatus
from phy.ui import app as ui_app

ID = "1904.12072"
AT = "2026-10-25T00:00:00+00:00"
PREAMBLE = "\\newcommand{\\paren}[1]{\\left(#1\\right)}\n"
FIGURES = r"""
\begin{figure}
\includegraphics[width=\linewidth]{figs/flow}
\caption{The normalizing flow {\it and} a coupling layer.}
\label{fig:flowdiag}
\end{figure}
\begin{figure}
\includegraphics{rejections}
\caption{Rejection runs.}
\label{fig:accepthistograms}
\end{figure}
"""
# The recorded draft's quotes, a preamble macro and two of its key figures (one PNG, one EPS);
# the third figure label is not in the source.
FLATTENED = SEED_LIKE.replace("\\begin{document}\n", PREAMBLE + "\\begin{document}\n").replace(
    "\\section{Conclusions}", FIGURES + "\\section{Conclusions}"
)


@pytest.fixture
def home(phy_home):
    phy_home.mkdir()
    for name in ["config.toml", "questions.yaml"]:
        (phy_home / name).write_bytes((files("phy") / "defaults" / name).read_bytes())
    db.connect(phy_home / "phy.db").close()
    return phy_home


def add_card(home, version=3, latest=3, status="draft"):
    """1904.12072 with the recorded draft as the Card of `version`, verified by `phy verify`."""
    conn = sqlite3.connect(home / "phy.db")
    with conn:
        conn.execute(
            "INSERT INTO papers VALUES (?, ?, ?, ?, 'abs', 'hep-lat', 'hep-lat', NULL,"
            " 'physics:hep-lat', ?, ?)",
            (
                ID,
                latest,
                "Flow-based generative models for Markov chain Monte Carlo",
                "Albergo, Kanwar, Shanahan",
                AT,
                AT,
            ),
        )
        for v in range(1, latest + 1):
            conn.execute(
                "INSERT INTO paper_versions (arxiv_id, version, submitted_at,"
                " first_seen_datestamp, source_type) VALUES (?, ?, ?, '2026-10-25', 'latex')",
                (ID, v, AT),
            )
        conn.execute(
            "INSERT INTO runs (id, stage, arxiv_id, status, started_at)"
            " VALUES ('read-1', 'read', ?, 'ok', ?)",
            (ID, AT),
        )
        conn.execute(
            "INSERT INTO cards (arxiv_id, version, card_json, status, model, prompt_version,"
            " schema_version, run_id, created_at, updated_at) VALUES (?, ?, ?, 'draft',"
            " 'claude-sonnet-5-5', 'v2', 'card/v1', 'read-1', ?, ?)",
            (ID, version, RECORDED_DRAFT.model_dump_json(), AT, AT),
        )
    paths = resolve_paths()
    paths.flattened(ID, version).parent.mkdir(parents=True)
    paths.flattened(ID, version).write_text(FLATTENED)
    tree = paths.source_tree(ID, version)
    (tree / "figs").mkdir(parents=True)
    buf = io.BytesIO()
    Image.new("RGB", (4, 3), "red").save(buf, "PNG")
    (tree / "figs" / "flow.png").write_bytes(buf.getvalue())
    (tree / "rejections.eps").write_text("%!PS-Adobe-3.0 EPSF-3.0")
    assert CliRunner().invoke(cli, ["verify"]).exit_code == 0
    if status != "verified":
        with conn:
            conn.execute("UPDATE cards SET status = ?", (status,))
    conn.close()


def get(path="/review"):
    response = TestClient(ui_app.create_app(resolve_paths())).get(path)
    assert response.status_code == 200
    return response


def page():
    return html.fromstring(get().text)


def field(doc, path):
    [el] = doc.xpath(f'//*[@data-field="{path}"]')
    return el


def text(el):
    return " ".join(el.text_content().split())


def shading(el):
    return {c for c in el.classes if c in ("s-inferred", "s-unsupported")}


def test_every_field_is_shown_in_card_order(home):
    add_card(home, status="verified")
    doc = page()
    labels = [text(el) for el in doc.xpath("//*[@data-field]/*[@class='flabel']/*[@class='name']")]
    assert labels == [
        "tl;dr",
        *[f"Result {i}" for i in range(1, 6)],
        *[f"Assumption {i}" for i in range(1, 4)],
        "System",
        "Method",
        "Baselines",
        "Claimed advance",
        "Code / data",
        *[f"Stated limitation {i}" for i in range(1, 4)],
        "Equation eq:acc-rej",
        "Equation eq:loss",
        "Equation eq:mean-acc-bound",
        "Figure fig:compare_autocorr",
        "Figure fig:accepthistograms",
        "Figure fig:flowdiag",
        "Research questions",
        *[f"Flagged limitation {i}" for i in range(1, 4)],
        "Deep read?",
    ]
    assert [text(s) for s in doc.xpath("//nav[@class='secnav']//a/*[@class='name']")] == [
        "Summary",
        "Setup",
        "Limitations",
        "Equations & figures",
        "Agent's opinion",
    ]
    subject = text(doc.xpath("//*[@class='subject']")[0])
    assert "1904.12072v3" in subject and "Albergo, Kanwar, Shanahan" in subject


def test_shading_follows_support(home):
    add_card(home, status="verified")
    doc = page()
    assert shading(field(doc, "key_results[0]")) == set()
    assert shading(field(doc, "key_results[1]")) == {"s-unsupported"}
    assert shading(field(doc, "method")) == {"s-inferred"}
    assert shading(field(doc, "system")) == {"s-unsupported"}
    code_data = field(doc, "code_data")
    assert shading(code_data) == set() and "none" in text(code_data)
    badges = text(doc.xpath("//*[@class='badges']")[0])
    assert "5 unsupported" in badges and "1 inferred" in badges
    assert "6 invented numbers" in badges


def test_quotes_are_folded_with_their_location(home):
    add_card(home, status="verified")
    doc = page()
    [quotes] = field(doc, "system").xpath(".//details[@class='ev']")
    assert "open" not in quotes.attrib
    assert 'Sec. "Results"' in text(quotes)
    assert "not found" in text(field(doc, "limitations_stated[1]").xpath(".//details")[0])
    assert "Abstract" in text(field(doc, "claimed_advance").xpath(".//details")[0])


def test_a_quote_matching_more_than_once_says_so(home):
    add_card(home, status="verified")
    conn = db.connect(home / "phy.db")
    card = json.loads(conn.execute("SELECT card_json FROM cards").fetchone()[0])
    card["key_results"][0]["evidence"][0]["match_count"] = 3
    with conn:
        conn.execute("UPDATE cards SET card_json = ?", (json.dumps(card),))
    assert "also appears 2× elsewhere" in text(field(page(), "key_results[0]"))


def test_number_pills_mark_ungrounded_and_invented_numbers(home):
    add_card(home, status="verified")
    doc = page()
    assert "8 ∉ quote" in text(field(doc, "method")) and "12 ∉ quote" in text(field(doc, "method"))
    assert "6.975 ∉ paper" in text(field(doc, "system"))


def test_warnings_are_grey_chips_on_their_section(home):
    add_card(home, status="verified")
    doc = page()
    [section] = doc.xpath("//section[@data-section='Equations & figures']")
    chips = [text(c) for c in section.xpath(".//*[contains(@class, 'warning')]")]
    assert any("fig:compare_autocorr" in c for c in chips)


def test_figures_resolve_from_the_source(home):
    add_card(home, status="verified")
    doc = page()
    [img] = field(doc, "key_figures[2]").xpath(".//img")
    assert (
        TestClient(ui_app.create_app(resolve_paths()))
        .get(img.get("src"))
        .content.startswith(b"\x89PNG")
    )
    assert "figure not renderable" in text(field(doc, "key_figures[1]"))
    assert "a coupling layer" in text(field(doc, "key_figures[2]"))


def test_katex_gets_the_preamble_macros(home):
    add_card(home, status="verified")
    assert '"\\\\paren": "\\\\left(#1\\\\right)"' in get().text


def test_the_opinion_is_one_dashed_block(home):
    add_card(home, status="verified")
    [section] = page().xpath("//section[contains(@class, 'opinion')]")
    assert section.get("data-section") == "Agent's opinion"


def test_a_stale_card_shows_the_stale_badge(home):
    add_card(home, version=2, latest=3, status="stale")
    badges = text(page().xpath("//*[@class='badges']")[0])
    assert "Stale" in badges


def test_an_empty_queue_says_so(home):
    assert "Nothing to review" in get().text


def test_the_release_badge_shows_when_an_update_is_available(home, monkeypatch):
    assert "update available" not in get().text
    monkeypatch.setattr(
        ui_app,
        "release_status",
        lambda paths: ReleaseStatus("v0.1.0", "v0.2.0", ["Add /review", "Fix Verify"]),
    )
    [badge] = page().xpath("//*[contains(@class, 'release')]")
    assert text(badge) == "update available: v0.2.0 (2 commits)"
    assert "Add /review" in badge.get("title") and "phy schedule update" in badge.get("title")


def test_phy_ui_serves_on_localhost_without_taking_the_lock(home, monkeypatch):
    import uvicorn

    from phy.locks import phy_lock

    served = {}
    monkeypatch.setattr(
        uvicorn, "run", lambda app, host, port, **kw: served.update(app=app, host=host, port=port)
    )
    with phy_lock(resolve_paths()):
        result = CliRunner().invoke(cli, ["ui"])
    assert result.exit_code == 0, result.output
    assert (served["host"], served["port"]) == ("127.0.0.1", 8000)
    assert TestClient(served["app"]).get("/review").status_code == 200


def test_a_macro_body_cannot_close_the_script_tag(home):
    add_card(home, status="verified")
    flattened = resolve_paths().flattened(ID, 3)
    flattened.write_text(
        "\\newcommand{\\evil}{</script><script>alert(1)</script>}\n" + flattened.read_text()
    )
    assert "<script>alert(1)" not in get().text
