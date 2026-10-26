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


def add_card(home, version=3, latest=3, status="draft", arxiv_id=ID):
    """A Paper (1904.12072 by default) with the recorded draft as the Card of `version`,
    verified by `phy verify`."""
    conn = sqlite3.connect(home / "phy.db")
    with conn:
        conn.execute(
            "INSERT INTO papers VALUES (?, ?, ?, ?, 'abs', 'hep-lat', 'hep-lat', NULL,"
            " 'physics:hep-lat', ?, ?)",
            (
                arxiv_id,
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
                (arxiv_id, v, AT),
            )
        conn.execute(
            "INSERT INTO runs (id, stage, arxiv_id, status, started_at)"
            " VALUES (?, 'read', ?, 'ok', ?)",
            (f"read-{arxiv_id}", arxiv_id, AT),
        )
        conn.execute(
            "INSERT INTO cards (arxiv_id, version, card_json, status, model, prompt_version,"
            " schema_version, run_id, created_at, updated_at) VALUES (?, ?, ?, 'draft',"
            " 'claude-sonnet-5-5', 'v2', 'card/v1', ?, ?, ?)",
            (arxiv_id, version, RECORDED_DRAFT.model_dump_json(), f"read-{arxiv_id}", AT, AT),
        )
    paths = resolve_paths()
    paths.flattened(arxiv_id, version).parent.mkdir(parents=True)
    paths.flattened(arxiv_id, version).write_text(FLATTENED)
    tree = paths.source_tree(arxiv_id, version)
    (tree / "figs").mkdir(parents=True)
    buf = io.BytesIO()
    Image.new("RGB", (4, 3), "red").save(buf, "PNG")
    (tree / "figs" / "flow.png").write_bytes(buf.getvalue())
    (tree / "rejections.eps").write_text("%!PS-Adobe-3.0 EPSF-3.0")
    assert CliRunner().invoke(cli, ["verify"]).exit_code == 0
    if status != "verified":
        with conn:
            conn.execute("UPDATE cards SET status = ? WHERE arxiv_id = ?", (status, arxiv_id))
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


OTHER = "2003.06413"


def client(clock=None):
    paths = resolve_paths()
    return TestClient(ui_app.create_app(paths, clock=clock) if clock else ui_app.create_app(paths))


def hidden_fields(doc):
    [form] = doc.xpath("//form[@id='verdict']")
    return {i.get("name"): i.get("value") for i in form.xpath(".//input[@type='hidden']")}


def test_saving_a_review_records_it_and_shows_the_next_card(home):
    add_card(home, status="verified")
    add_card(home, status="verified", arxiv_id=OTHER)
    now = [1000.0]
    web = client(clock=lambda: now[0])
    doc = html.fromstring(web.get("/review").text)
    assert ID in text(doc.xpath("//*[@class='subject']")[0])
    now[0] += 192.6
    response = web.post(
        "/reviews",
        data={**hidden_fields(doc), "relevance": "partly", "deep_read": "1", "note": "eq 3?"},
    )
    assert response.status_code == 200
    assert OTHER in text(html.fromstring(response.text).xpath("//*[@class='subject']")[0])
    conn = db.connect(home / "phy.db")
    rows = conn.execute("SELECT relevance, deep_read, seconds_spent, note FROM reviews").fetchall()
    assert [tuple(r) for r in rows] == [("partly", 1, 193, "eq 3?")]
    assert db.get_card(conn, ID, 3)["status"] == "reviewed"
    assert db.get_card(conn, OTHER, 3)["status"] == "verified"


def test_a_stale_card_rated_relevant_stays_stale_and_is_queued_for_a_re_read(home):
    add_card(home, version=2, latest=3, status="stale")
    web = client()
    form = hidden_fields(html.fromstring(web.get("/review").text))
    assert web.post("/reviews", data={**form, "relevance": "yes"}).status_code == 200
    conn = db.connect(home / "phy.db")
    assert db.get_card(conn, ID, 2)["status"] == "stale"
    assert [r["arxiv_id"] for r in db.stale_cards(conn, relevant_only=True)] == [ID]
    assert "Nothing to review" in web.get("/review").text


def test_a_card_is_reviewed_once(home):
    add_card(home, status="verified")
    web = client()
    form = {**hidden_fields(html.fromstring(web.get("/review").text)), "relevance": "no"}
    assert web.post("/reviews", data=form).status_code == 200
    assert web.post("/reviews", data=form).status_code == 409
    conn = db.connect(home / "phy.db")
    assert conn.execute("SELECT count(*) FROM reviews").fetchone()[0] == 1


def chips(doc, path):
    return [text(c) for c in field(doc, path).xpath(".//*[contains(@class, 'flagchip')]")]


def test_flags_show_as_chips_and_can_be_removed_before_save(home):
    add_card(home, status="verified")
    web = client()
    card_id = hidden_fields(html.fromstring(web.get("/review").text))["card_id"]
    flag = {"card_id": card_id, "field_path": "key_results[1]"}
    response = web.post("/flags", data={**flag, "kind": "wrong_value", "note": "N is 14, not 16"})
    assert response.status_code == 200
    assert "Wrong value: N is 14, not 16" in text(html.fromstring(response.text))
    assert web.post("/flags", data={**flag, "kind": "missing"}).status_code == 200
    doc = html.fromstring(web.get("/review").text)
    assert chips(doc, "key_results[1]") == ["⚑ Wrong value: N is 14, not 16 ×", "⚑ Missing ×"]
    assert chips(doc, "key_results[0]") == []
    [remove] = field(doc, "key_results[1]").xpath(".//*[contains(@class, 'flagchip')][1]//button")
    assert web.delete(remove.get("hx-delete")).status_code == 200
    doc = html.fromstring(web.get("/review").text)
    assert chips(doc, "key_results[1]") == ["⚑ Missing ×"]
    conn = db.connect(home / "phy.db")
    rows = conn.execute("SELECT field_path, kind, note FROM flags").fetchall()
    assert [tuple(r) for r in rows] == [("key_results[1]", "missing", None)]


def test_a_flag_kind_must_be_one_of_the_four(home):
    add_card(home, status="verified")
    web = client()
    card_id = hidden_fields(html.fromstring(web.get("/review").text))["card_id"]
    flag = {"card_id": card_id, "field_path": "method", "kind": "typo"}
    assert web.post("/flags", data=flag).status_code == 422
    conn = db.connect(home / "phy.db")
    assert conn.execute("SELECT count(*) FROM flags").fetchone()[0] == 0


def test_flags_are_fixed_once_the_review_is_saved(home):
    add_card(home, status="verified")
    web = client()
    form = hidden_fields(html.fromstring(web.get("/review").text))
    flag = {"card_id": form["card_id"], "field_path": "method", "kind": "missing"}
    assert web.post("/flags", data=flag).status_code == 200
    assert web.post("/reviews", data={**form, "relevance": "no"}).status_code == 200
    assert web.post("/flags", data=flag).status_code == 409
    conn = db.connect(home / "phy.db")
    [flag_id] = conn.execute("SELECT id FROM flags").fetchone()
    assert web.delete(f"/flags/{flag_id}").status_code == 409


def test_markdown_export_holds_every_field_value_and_the_review(home):
    add_card(home, status="verified")
    web = client()
    form = hidden_fields(html.fromstring(web.get("/review").text))
    flag = {"card_id": form["card_id"], "field_path": "method", "kind": "missing", "note": "dims"}
    web.post("/flags", data=flag)
    review = {**form, "relevance": "yes", "deep_read": "1", "note": "read section 4"}
    web.post("/reviews", data=review)
    response = web.get(f"/cards/{form['card_id']}/export.md")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert 'filename="1904.12072v3.md"' in response.headers["content-disposition"]
    md = response.text
    d = RECORDED_DRAFT
    values = [d.tldr, d.opinion.deep_read.why]
    values += [f.value for f in [*d.key_results, *d.assumptions, *d.limitations_stated]]
    values += [f.value for f in [d.system, d.method, d.baselines, d.claimed_advance] if f]
    values += [e.latex for e in d.key_equations] + [e.meaning for e in d.key_equations]
    values += [f.why for f in d.key_figures] + [q.why for q in d.questions]
    values += [f.value for f in d.opinion.limitations_flagged]
    assert [v for v in values if v not in md] == []
    assert "Flow-based generative models for Markov chain Monte Carlo" in md
    assert "Relevance: yes" in md and "Deep read: yes" in md and "read section 4" in md
    assert "Missing: dims" in md


def test_markdown_export_before_the_review_says_there_is_none(home):
    add_card(home, status="verified")
    web = client()
    card_id = hidden_fields(html.fromstring(web.get("/review").text))["card_id"]
    assert "Not reviewed yet" in web.get(f"/cards/{card_id}/export.md").text
