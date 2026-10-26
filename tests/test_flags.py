from datetime import UTC, datetime, timedelta
from importlib.resources import files

import pytest
from typer.testing import CliRunner

from phy import db
from phy.cli import app

NOW = datetime.now(UTC)


def ago(**delta):
    return (NOW - timedelta(**delta)).isoformat(timespec="seconds")


@pytest.fixture
def seeded(phy_home):
    phy_home.mkdir()
    for name in ["config.toml", "questions.yaml"]:
        (phy_home / name).write_bytes((files("phy") / "defaults" / name).read_bytes())
    conn = db.connect(phy_home / "phy.db")
    with conn:
        conn.execute(
            "INSERT INTO runs (id, stage, status, started_at) VALUES ('r', 'read', 'ok', ?)",
            (ago(days=60),),
        )
        for card_id, arxiv_id in [(1, "1904.12072"), (2, "2003.06413")]:
            conn.execute(
                "INSERT INTO papers VALUES (?, 1, 't', 'a', 'x', 'hep-lat', 'hep-lat', NULL,"
                " 'physics:hep-lat', ?, ?)",
                (arxiv_id, ago(days=60), ago(days=60)),
            )
            conn.execute(
                "INSERT INTO paper_versions (arxiv_id, version, submitted_at,"
                " first_seen_datestamp) VALUES (?, 1, ?, '2026-08-01')",
                (arxiv_id, ago(days=60)),
            )
            conn.execute(
                "INSERT INTO cards (id, arxiv_id, version, card_json, status, model,"
                " prompt_version, schema_version, run_id, created_at, updated_at)"
                " VALUES (?, ?, 1, '{}', 'reviewed', 'm', 'v2', 'card/v1', 'r', ?, ?)",
                (card_id, arxiv_id, ago(days=60), ago(days=60)),
            )
        conn.executemany(
            "INSERT INTO flags (card_id, field_path, kind, note, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            [
                (1, "key_results[1]", "wrong_value", "N is 14", ago(days=2)),
                (2, "key_results[0]", "wrong_value", None, ago(days=5)),
                (2, "key_results[3]", "missing", "no error bars", ago(days=5)),
                (1, "opinion.limitations_flagged[0]", "should_be_opinion", None, ago(days=1)),
                (1, "method", "quote_doesnt_support", "too old", ago(days=45)),
            ],
        )
    conn.close()


def test_flags_are_grouped_by_field_and_kind(seeded):
    result = CliRunner().invoke(app, ["flags", "--since", "30d"])
    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[1:] == [
        "key_results: 3",
        "  wrong_value: 2",
        "    1904.12072v1 key_results[1]: N is 14",
        "    2003.06413v1 key_results[0]",
        "  missing: 1",
        "    2003.06413v1 key_results[3]: no error bars",
        "opinion.limitations_flagged: 1",
        "  should_be_opinion: 1",
        "    1904.12072v1 opinion.limitations_flagged[0]",
    ]
    assert result.output.splitlines()[0].endswith("4 Flags")


def test_a_longer_window_reaches_older_flags(seeded):
    result = CliRunner().invoke(app, ["flags", "--since", "60d"])
    assert "method: 1" in result.output and "too old" in result.output


def test_the_window_is_30_days_by_default(seeded):
    result = CliRunner().invoke(app, ["flags"])
    assert result.exit_code == 0, result.output
    assert result.output.startswith("last 30 days: 4 Flags")


def test_invalid_config_fails_the_command(seeded, phy_home):
    (phy_home / "config.toml").write_text("nonsense = 1\n")
    assert CliRunner().invoke(app, ["flags"]).exit_code == 1


def test_since_takes_days(seeded):
    result = CliRunner().invoke(app, ["flags", "--since", "a month"])
    assert result.exit_code != 0
