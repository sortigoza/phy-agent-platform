import re
import tomllib
import typing
from datetime import UTC, datetime
from importlib.resources import files

from phy import db
from phy.config import Config
from phy.ui import monitor
from phy.ui.app import FlagKind
from phy.ui.help import HELP, MONITOR_KEYS, REVIEW_KEYS
from phy.ui.review import FLAG_KINDS
from phy.verify import CardWarning

TEMPLATES = files("phy") / "ui" / "templates"
HELP_KEY = re.compile(r"help\.(\w+)|help\[['\"](\w+)['\"]\]")


def test_every_hover_key_in_the_templates_exists():
    used = {
        a or b
        for entry in TEMPLATES.iterdir()
        if entry.name.endswith(".html")
        for a, b in HELP_KEY.findall(entry.read_text())
    }
    assert used, "the scan found no keys"
    assert used - HELP.keys() == set()


def test_every_warning_kind_has_hover_help():
    kinds = typing.get_args(typing.get_type_hints(CardWarning)["kind"])
    assert set(kinds) - HELP.keys() == set()


def test_every_key_in_the_key_lists_has_hover_help():
    assert {name for _, name in REVIEW_KEYS + MONITOR_KEYS} - HELP.keys() == set()


def test_every_monitor_tile_and_funnel_step_has_hover_help(phy_home):
    phy_home.mkdir()
    conn = db.connect(phy_home / "phy.db")
    config = Config.model_validate(
        tomllib.loads((files("phy") / "defaults" / "config.toml").read_text())
    )
    tiles = monitor.instruments(conn, config, datetime(2026, 10, 22, tzinfo=UTC))
    conn.close()
    keys = {f"i_{t.key}" for t in tiles} | {f"f_{key}" for key in monitor.FUNNEL_STEPS}
    assert len(keys) == len(tiles) + len(monitor.FUNNEL_STEPS)
    links = {f"{kind}link" for kind in ["eval", "card", "runs"]}
    assert (keys | links) - HELP.keys() == set()


def test_every_flag_kind_has_a_label_and_hover_help():
    assert list(FLAG_KINDS) == list(typing.get_args(FlagKind))
    assert set(FLAG_KINDS) - HELP.keys() == set()
