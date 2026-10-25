"""Paid smoke test: one real Read of 1904.12072 (about $0.10). Run with `pytest -m live`."""

import json
import os
import sqlite3
from importlib.resources import files

import pytest
from typer.testing import CliRunner

from phy.card import CardDraft
from phy.cli import app

# Captured at import, before the autouse fixture strips credentials from the environment.
REAL_ENV = {
    k: os.environ[k]
    for k in ["HOME", "ANTHROPIC_API_KEY", "ANTHROPIC_PROFILE", "ANTHROPIC_CONFIG_DIR"]
    if k in os.environ
}

pytestmark = pytest.mark.live


def test_read_1904_12072_for_real(phy_home, monkeypatch):
    for key, value in REAL_ENV.items():
        monkeypatch.setenv(key, value)
    phy_home.mkdir()
    for name in ["config.toml", "questions.yaml"]:
        (phy_home / name).write_bytes((files("phy") / "defaults" / name).read_bytes())

    result = CliRunner().invoke(app, ["read", "--paper", "1904.12072"])

    assert result.exit_code == 0, result.output
    conn = sqlite3.connect(phy_home / "phy.db")
    conn.row_factory = sqlite3.Row
    [card] = conn.execute("SELECT * FROM cards").fetchall()
    CardDraft.model_validate_json(card["card_json"])
    [run] = conn.execute("SELECT * FROM runs").fetchall()
    assert run["status"] == "ok"
    # The paper is written to the cache, unless a run in the last 5 minutes already did that.
    assert run["cache_write_tokens"] > 20_000 or run["cache_read_tokens"] > 20_000
    [line] = [json.loads(x) for x in (phy_home / run["log_path"]).open()]
    assert line["response"]["stop_reason"] == "end_turn"
