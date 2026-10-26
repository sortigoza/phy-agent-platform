import re
import typing
from importlib.resources import files

from phy.ui.help import HELP
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
