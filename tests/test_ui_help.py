import re
import typing
from importlib.resources import files

from phy.ui.app import FlagKind
from phy.ui.help import HELP, REVIEW_KEYS
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


def test_every_key_in_the_key_list_has_hover_help():
    assert {name for _, name in REVIEW_KEYS} - HELP.keys() == set()


def test_every_flag_kind_has_a_label_and_hover_help():
    assert list(FLAG_KINDS) == list(typing.get_args(FlagKind))
    assert set(FLAG_KINDS) - HELP.keys() == set()
