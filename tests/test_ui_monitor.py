from datetime import UTC, datetime
from importlib.resources import files

import pytest
from fastapi.testclient import TestClient
from lxml import html

from phy import db
from phy.config import resolve_paths
from phy.ui import app as ui_app

# Thursday 2026-10-22, 12:00 UTC.
NOW = datetime(2026, 10, 22, 12, tzinfo=UTC).timestamp()


@pytest.fixture
def home(phy_home):
    phy_home.mkdir()
    for name in ["config.toml", "questions.yaml"]:
        (phy_home / name).write_bytes((files("phy") / "defaults" / name).read_bytes())
    db.connect(phy_home / "phy.db").close()
    return phy_home


def execute(home, sql, *params):
    conn = db.connect(home / "phy.db")
    with conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(sql, params)
    conn.close()


def run(home, run_id, stage, started_at, status="ok", arxiv_id=None, cost=None):
    execute(
        home,
        "INSERT INTO runs (id, stage, arxiv_id, status, cost_usd, started_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        run_id,
        stage,
        arxiv_id,
        status,
        cost,
        started_at,
    )


def get():
    app = ui_app.create_app(resolve_paths(), clock=lambda: NOW)
    response = TestClient(app).get("/monitor")
    assert response.status_code == 200, response.text
    return html.fromstring(response.text)


def text(el):
    return " ".join(el.text_content().split())


def test_with_nothing_red_the_action_list_is_one_all_green_line(home):
    doc = get()
    [actions] = doc.xpath("//section[@id='sec-actions']")
    assert text(actions) == "All green."
    assert text(doc.xpath("//span[@data-red]")[0]) == "0 red"


def test_each_red_tile_is_one_action_line_and_counts_in_the_top_bar(home):
    run(home, "f1", "read", "2026-10-21T06:00:00+00:00", "failed", "2610.00001")
    run(home, "big", "read", "2026-10-21T07:00:00+00:00", cost=19.0)
    doc = get()
    assert text(doc.xpath("//span[@data-red]")[0]) == "2 red"
    lines = doc.xpath("//section[@id='sec-actions']//li")
    assert [li.get("data-tile") for li in lines] == ["failures", "spend"]
    failures = lines[0]
    assert failures.xpath(".//a[1]/@href") == ["#tile-failures"]
    assert "Open the run viewer" in text(failures)
    assert failures.xpath(".//a[@class='runs']/@href") == [
        "/runs?stage=read&status=failed&ids=2610.00001"
    ]
    assert "$19.00 / $20" in text(lines[1])


def test_tiles_are_grouped_under_their_question_with_a_pill_each(home):
    doc = get()
    groups = {
        s.get("id"): [t.get("id") for t in s.xpath(".//*[@data-state]")]
        for s in doc.xpath("//section[starts-with(@id, 'sec-')]")
    }
    assert groups["sec-running"] == ["tile-harvested", "tile-hwm_days", "tile-failures"]
    assert groups["sec-funnel"] == ["tile-candidates"]
    assert len(sum(groups.values(), [])) == 14
    pills = doc.xpath("//nav[contains(@class, 'secnav')]/a/@href")
    assert pills == [
        "#sec-actions",
        "#sec-strip",
        "#sec-running",
        "#sec-funnel",
        "#sec-right",
        "#sec-useful",
        "#sec-affordable",
    ]


def test_a_grey_tile_says_why(home):
    [tile] = get().xpath("//*[@id='tile-review_time']")
    assert tile.get("data-state") == "grey"
    assert "no Reviews yet" in text(tile)


def test_a_tile_shows_its_rule_note_link_and_7_bars(home):
    run(home, "sun", "read", "2026-10-18T06:00:00+00:00", cost=1.0)
    [tile] = get().xpath("//*[@id='tile-spend']")
    assert "red at 90%" in text(tile)
    assert "last week $1.00" in text(tile)
    assert tile.xpath(".//a[@class='runs']/@href") == ["/runs?since=week"]
    bars = tile.xpath(".//*[local-name()='rect']")
    assert len(bars) == 7
    assert ["we" in b.get("class") for b in bars] == [False, True, True, False, False, False, False]


def test_the_funnel_strip_shows_counts_shares_and_skipped(home):
    run(home, "f", "filter", "2026-10-21T06:00:00+00:00")
    for i, prefilter in enumerate(["pass", "pass", "fail", "pass"]):
        execute(
            home,
            "INSERT INTO screenings (arxiv_id, version, prefilter, screened_in, run_id, created_at)"
            " VALUES (?, 1, ?, ?, 'f', '')",
            f"2610.0000{i}",
            prefilter,
            int(i == 0),
        )
    run(home, "s", "read", "2026-10-21T06:00:00+00:00", "skipped", "2610.00009")
    [strip] = get().xpath("//section[@id='sec-strip']")
    steps = [text(s) for s in strip.xpath(".//*[@data-step]")]
    assert steps[1] == "3 Candidates"
    assert steps[2] == "1 Screened in 33%"
    assert "skipped as too long: 1" in text(strip)
