from datetime import UTC, datetime, timedelta
from importlib.resources import files

import pytest
from typer.testing import CliRunner

from phy import db
from phy import status as phy_status
from phy.cli import app
from phy.config import resolve_paths
from phy.locks import phy_lock
from phy.release import ReleaseStatus

NOW = datetime.now(UTC)


def ago(**delta):
    return (NOW - timedelta(**delta)).isoformat(timespec="seconds")


@pytest.fixture
def seeded(phy_home):
    phy_home.mkdir()
    for name in ["config.toml", "questions.yaml"]:
        (phy_home / name).write_bytes((files("phy") / "defaults" / name).read_bytes())
    conn = db.connect(phy_home / "phy.db")
    db.set_state(conn, "watch.hwm", "2026-10-24")
    db.set_state(conn, "watch.last_success_at", "2026-10-25T06:00:12+00:00")
    run = "INSERT INTO runs (id, stage, arxiv_id, status, error, cost_usd, started_at)"
    run += " VALUES (?, ?, ?, ?, ?, ?, ?)"
    conn.executemany(
        run,
        [
            ("f", "filter", None, "ok", None, 0.01, ago(hours=2)),
            ("old-filter", "filter", None, "ok", None, 0.01, ago(days=9)),
            ("r1", "read", "2610.00001", "ok", None, 0.10, ago(hours=1)),
            ("r2", "read", "2610.00002", "ok", None, 0.12, ago(hours=1)),
            # retried: an ok run of the same Stage and Paper since
            ("r3-fail", "read", "2610.00003", "failed", "boom", 0.0, ago(days=2)),
            ("r3", "read", "2610.00003", "ok", None, 0.09, ago(days=1)),
            # not retried
            ("r4-fail", "read", "2610.00004", "failed", "HTTP 404 for /src/", 0.0, ago(hours=3)),
            ("w-fail", "watch", None, "failed", "arXiv unavailable", None, ago(hours=4)),
        ],
    )
    for n, first_seen in [(1, 1), (2, 1), (3, 2), (4, 2), (5, 20)]:
        aid = f"2610.0000{n}"
        conn.execute(
            "INSERT INTO papers VALUES (?, 1, 't', 'a', 'x', 'hep-lat', 'hep-lat', NULL,"
            " 'physics:hep-lat', ?, ?)",
            (aid, ago(days=first_seen), ago(days=first_seen)),
        )
        conn.execute(
            "INSERT INTO paper_versions (arxiv_id, version, submitted_at, first_seen_datestamp)"
            " VALUES (?, 1, ?, ?)",
            (aid, ago(days=first_seen), (NOW - timedelta(days=first_seen)).date().isoformat()),
        )
    screening = "INSERT INTO screenings (arxiv_id, version, prefilter, best_score, screened_in,"
    screening += " run_id, created_at) VALUES (?, 1, ?, ?, ?, ?, ?)"
    conn.executemany(
        screening,
        [
            ("2610.00001", "skipped", 0.9, 1, "f", ago(hours=2)),
            ("2610.00002", "pass", 0.6, 1, "f", ago(hours=2)),
            ("2610.00003", "pass", 0.3, 0, "f", ago(hours=2)),
            ("2610.00004", "fail", None, 0, "f", ago(hours=2)),
            ("2610.00005", "skipped", 0.9, 1, "old-filter", ago(days=9)),
        ],
    )
    card = "INSERT INTO cards (arxiv_id, version, card_json, status, model, prompt_version,"
    card += " schema_version, run_id, created_at, updated_at) VALUES (?, 1, '{}', ?, 'm', 'v2',"
    card += " 'card/v1', ?, ?, ?)"
    conn.executemany(
        card,
        [
            ("2610.00001", "reviewed", "r1", ago(hours=1), ago(hours=1)),
            ("2610.00002", "draft", "r2", ago(hours=1), ago(hours=1)),
        ],
    )
    conn.execute(
        "INSERT INTO reviews (card_id, relevance, deep_read, seconds_spent, created_at)"
        " VALUES (1, 'partly', 1, 240, ?)",
        (ago(minutes=30),),
    )
    conn.commit()
    conn.close()
    return phy_home


def phy(*args):
    return CliRunner().invoke(app, list(args))


def test_status_on_a_seeded_db(seeded):
    result = phy("status")

    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0] == "watch: mark 2026-10-24, last success 2026-10-25 06:00 UTC"
    assert lines[1] == (
        "funnel (7 days): 4 harvested, 3 candidates, 2 screened in, 2 carded, 1 verified,"
        " 1 reviewed, 1 relevant, 1 deep read"
    )
    assert lines[2].startswith("spend (ISO week from ")
    assert lines[2].endswith("of $20.00")
    assert "failures not retried (2):" in lines[3]
    assert "read 2610.00004 r4-fail: HTTP 404 for /src/" in result.stdout
    assert "watch w-fail: arXiv unavailable" in result.stdout
    assert "2610.00003" not in result.stdout
    assert lines[-1] == "release: none installed"


def test_status_says_when_the_guardrail_is_reached(seeded):
    conn = db.connect(seeded / "phy.db")
    conn.execute(
        "INSERT INTO runs (id, stage, status, cost_usd, started_at) VALUES"
        " ('big', 'read', 'ok', 25.0, ?)",
        (ago(minutes=1),),
    )
    conn.commit()
    conn.close()

    result = phy("status")

    assert "guardrail reached: Read selects nothing until Monday" in result.stdout


def test_status_on_a_fresh_install(phy_home):
    phy_home.mkdir()
    for name in ["config.toml", "questions.yaml"]:
        (phy_home / name).write_bytes((files("phy") / "defaults" / name).read_bytes())

    result = phy("status")

    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[0] == "watch: no mark yet, never succeeded"
    assert "failures not retried: none" in result.stdout


def test_status_does_not_take_the_lock(seeded):
    with phy_lock(resolve_paths()):
        result = phy("status")

    assert result.exit_code == 0
    assert result.stdout.startswith("watch: mark")


@pytest.mark.parametrize(
    "release, line",
    [
        (
            ReleaseStatus("v0.1.0", "v0.2.0", ["Fix Verify", "Add /review"]),
            "release: v0.1.0; update available: v0.2.0 (2 commits), run `phy schedule update`",
        ),
        (ReleaseStatus("v0.2.0", "v0.2.0"), "release: v0.2.0 (newest)"),
        # the newest tag does not contain the installed one: not an update
        (ReleaseStatus("v0.2.0", "v0.1.0"), "release: v0.2.0 (newest)"),
    ],
)
def test_status_names_the_installed_release_and_any_update(seeded, monkeypatch, release, line):
    monkeypatch.setattr(phy_status, "release_status", lambda paths: release)
    assert phy("status").stdout.splitlines()[-1] == line
