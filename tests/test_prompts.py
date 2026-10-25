import pytest

from phy import prompts
from phy.card import SCHEMA_VERSION
from phy.prompts import PromptError

READ = """\
---
stage: read
version: v9
system: shared/v1
model: claude-sonnet-5-5
effort: medium
schema: card/v1
params: [questions, authors]
notes: A test prompt.
---
By {{authors}}: keep $\\phi^4$ and $L=16$ as written.

{{questions}}
"""


@pytest.fixture
def directory(tmp_path):
    (tmp_path / "read").mkdir()
    (tmp_path / "read" / "v9.md").write_text(READ)
    return tmp_path


def test_front_matter_is_parsed(directory):
    prompt = prompts.load("read", "v9", directory)
    assert prompt.stage == "read"
    assert prompt.version == "v9"
    assert prompt.system == "shared/v1"
    assert prompt.model == "claude-sonnet-5-5"
    assert prompt.effort == "medium"
    assert prompt.schema_version == "card/v1"
    assert prompt.params == ["questions", "authors"]
    assert prompt.body.startswith("By {{authors}}")


def test_render_fills_placeholders_and_leaves_latex_dollars_alone(directory):
    text = prompts.load("read", "v9", directory).render(questions="- Q1. Flows", authors="A. B")
    assert text == "By A. B: keep $\\phi^4$ and $L=16$ as written.\n\n- Q1. Flows"


def test_a_missing_placeholder_value_raises(directory):
    with pytest.raises(PromptError, match="authors"):
        prompts.load("read", "v9", directory).render(questions="x")


def test_an_unused_value_raises(directory):
    with pytest.raises(PromptError, match="extra"):
        prompts.load("read", "v9", directory).render(questions="x", authors="y", extra="z")


def test_params_must_match_the_placeholders_in_the_body(directory):
    (directory / "read" / "v8.md").write_text(READ.replace("[questions, authors]", "[questions]"))
    with pytest.raises(PromptError, match="authors"):
        prompts.load("read", "v8", directory)


def test_unknown_front_matter_keys_are_refused(directory):
    (directory / "read" / "v7.md").write_text(READ.replace("notes:", "used_by: [x]\nnotes:"))
    with pytest.raises(PromptError, match="used_by"):
        prompts.load("read", "v7", directory)


def test_a_missing_prompt_names_its_path(directory):
    with pytest.raises(PromptError, match="v1.md"):
        prompts.load("read", "v1", directory)


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_shipped_read_prompts_pair_with_the_shared_prompt_and_the_card_schema(version):
    prompt = prompts.load("read", version)
    assert prompt.system == "shared/v1"
    assert prompt.schema_version == SCHEMA_VERSION
    prompts.load(*prompt.system.split("/"))


def test_read_v2_adds_the_authors():
    v1, v2 = prompts.load("read", "v1"), prompts.load("read", "v2")
    assert v1.params == ["questions"]
    assert v2.params == ["questions", "authors"]
    text = v2.render(questions="- Q1", authors="M. S. Albergo, G. Kanwar, P. E. Shanahan")
    assert "Albergo" in text
    assert "et al." in text
    assert "acronym" in text
