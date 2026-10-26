import pytest

from phy import db

AT = "2026-10-25T00:00:00+00:00"


@pytest.fixture
def conn(phy_home):
    phy_home.mkdir()
    conn = db.connect(phy_home / "phy.db")
    conn.execute(
        "INSERT INTO runs (id, stage, status, started_at) VALUES ('r', 'read', 'ok', ?)", (AT,)
    )
    yield conn
    conn.close()


def paper(conn, arxiv_id, latest=1):
    conn.execute(
        "INSERT INTO papers VALUES (?, ?, 't', 'a', 'x', 'hep-lat', 'hep-lat', NULL,"
        " 'physics:hep-lat', ?, ?)",
        (arxiv_id, latest, AT, AT),
    )
    for v in range(1, latest + 1):
        conn.execute(
            "INSERT INTO paper_versions (arxiv_id, version, submitted_at, first_seen_datestamp)"
            " VALUES (?, ?, ?, '2026-10-25')",
            (arxiv_id, v, AT),
        )


def card(conn, arxiv_id, status, version=1, score=None, reviewed=False):
    if score is not None:
        conn.execute(
            "INSERT INTO screenings (arxiv_id, version, prefilter, best_score, screened_in,"
            " run_id, created_at) VALUES (?, ?, 'pass', ?, 1, 'r', ?)",
            (arxiv_id, version, score, AT),
        )
    card_id = conn.execute(
        "INSERT INTO cards (arxiv_id, version, card_json, status, model, prompt_version,"
        " schema_version, run_id, created_at, updated_at)"
        " VALUES (?, ?, '{}', ?, 'm', 'v2', 'card/v1', 'r', ?, ?) RETURNING id",
        (arxiv_id, version, status, AT, AT),
    ).fetchone()[0]
    if reviewed:
        conn.execute(
            "INSERT INTO reviews (card_id, relevance, created_at) VALUES (?, 'yes', ?)",
            (card_id, AT),
        )


def queue(conn):
    return [(r["arxiv_id"], r["version"]) for r in db.review_queue(conn)]


def test_unreviewed_verified_cards_by_best_score_with_unscreened_first(conn):
    for arxiv_id in ["2610.00001", "2610.00002", "2610.00003", "2610.00004"]:
        paper(conn, arxiv_id)
    card(conn, "2610.00001", "verified", score=0.5)
    card(conn, "2610.00002", "verified", score=0.9)
    card(conn, "2610.00003", "verified")  # read --paper: no screening
    card(conn, "2610.00004", "verified", score=0.6)
    assert queue(conn) == [
        ("2610.00003", 1),
        ("2610.00002", 1),
        ("2610.00004", 1),
        ("2610.00001", 1),
    ]


def test_drafts_and_reviewed_cards_are_not_queued(conn):
    for arxiv_id in ["2610.00001", "2610.00002", "2610.00003"]:
        paper(conn, arxiv_id)
    card(conn, "2610.00001", "draft", score=0.9)
    card(conn, "2610.00002", "reviewed", score=0.9, reviewed=True)
    card(conn, "2610.00003", "verified", score=0.9, reviewed=True)
    assert queue(conn) == []


def test_an_unreviewed_stale_card_is_queued_until_its_paper_is_carded_again(conn):
    paper(conn, "2610.00001", latest=2)
    paper(conn, "2610.00002", latest=2)
    card(conn, "2610.00001", "stale", score=0.7)
    card(conn, "2610.00002", "stale", score=0.8)
    card(conn, "2610.00002", "verified", version=2, score=0.6)
    assert queue(conn) == [("2610.00001", 1), ("2610.00002", 2)]


def test_a_verified_card_stays_queued_when_a_newer_version_is_carded(conn):
    paper(conn, "2610.00001", latest=2)
    card(conn, "2610.00001", "verified", score=0.7)
    card(conn, "2610.00001", "draft", version=2)
    assert queue(conn) == [("2610.00001", 1)]
