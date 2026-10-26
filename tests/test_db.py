import shutil
import sqlite3
from importlib.resources import files

import pytest

from phy import db


def latest_migration() -> int:
    return max(
        int(p.name[:3]) for p in (files("phy") / "migrations").iterdir() if p.name.endswith(".sql")
    )


def test_fresh_db_reaches_latest_version_with_state_and_runs(tmp_path):
    conn = db.connect(tmp_path / "phy.db")
    assert conn.execute("PRAGMA user_version").fetchone()[0] == latest_migration()
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"state", "runs"} <= tables
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] > 0


def test_reconnect_applies_nothing(tmp_path):
    db.connect(tmp_path / "phy.db").execute(
        "INSERT INTO state VALUES ('k', 'v', 'now')"
    ).connection.commit()
    conn = db.connect(tmp_path / "phy.db")
    assert conn.execute("SELECT value FROM state WHERE key = 'k'").fetchone()[0] == "v"


def test_new_numbered_migration_is_applied_once(tmp_path):
    migrations = tmp_path / "migrations"
    shutil.copytree(files("phy") / "migrations", migrations)
    db.connect(tmp_path / "phy.db", migrations)
    nxt = latest_migration() + 1
    (migrations / f"{nxt:03d}_extra.sql").write_text("CREATE TABLE extra (id INTEGER PRIMARY KEY);")

    conn = db.connect(tmp_path / "phy.db", migrations)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == nxt
    conn = db.connect(
        tmp_path / "phy.db", migrations
    )  # would fail with "table extra already exists"
    assert conn.execute("PRAGMA user_version").fetchone()[0] == nxt


def test_failing_migration_leaves_db_at_previous_version(tmp_path):
    migrations = tmp_path / "migrations"
    shutil.copytree(files("phy") / "migrations", migrations)
    nxt = latest_migration() + 1
    (migrations / f"{nxt:03d}_broken.sql").write_text(
        "CREATE TABLE half (id INTEGER); SELECT nonsense(;"
    )
    with pytest.raises(sqlite3.OperationalError):
        db.connect(tmp_path / "phy.db", migrations)
    conn = db.connect(tmp_path / "phy.db")
    assert conn.execute("PRAGMA user_version").fetchone()[0] == latest_migration()
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "half" not in tables


def test_state_round_trip(tmp_path):
    conn = db.connect(tmp_path / "phy.db")
    assert db.get_state(conn, "watch.hwm") is None
    db.set_state(conn, "watch.hwm", "2026-10-20")
    db.set_state(conn, "watch.hwm", "2026-10-21")
    assert db.get_state(conn, "watch.hwm") == "2026-10-21"


def test_two_migrations_with_one_number_are_refused(tmp_path):
    migrations = tmp_path / "migrations"
    shutil.copytree(files("phy") / "migrations", migrations)
    nxt = latest_migration() + 1
    (migrations / f"{nxt:03d}_a.sql").write_text("CREATE TABLE a (id INTEGER);")
    (migrations / f"{nxt:03d}_b.sql").write_text("CREATE TABLE b (id INTEGER);")
    with pytest.raises(RuntimeError, match="share a number"):
        db.connect(tmp_path / "phy.db", migrations)


def test_run_lookups_by_time_and_by_stage_and_paper_use_an_index(tmp_path):
    conn = db.connect(tmp_path / "phy.db")

    def plan(sql: str) -> str:
        return " ".join(r["detail"] for r in conn.execute("EXPLAIN QUERY PLAN " + sql))

    assert "USING INDEX" in plan("SELECT * FROM runs WHERE started_at >= '2026-10-19'")
    # the unretried-failure check: a later ok run of the same Stage and paper
    retried = plan(
        "SELECT 1 FROM runs WHERE stage = 'read' AND arxiv_id IS '1904.12072'"
        " AND status = 'ok' AND started_at > '2026-10-19'"
    )
    assert "(stage=? AND arxiv_id=? AND started_at>?)" in retried
