"""Prompt files: `prompts/<stage>/<version>.md`, YAML front matter then the body.

Placeholders are `{{name}}`, filled by plain replacement, never `$name`, because prompt text
contains LaTeX `$`. A placeholder without a value, or a value without a placeholder, is an
error. A file is immutable once used; config selects the active version.
"""

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from phy.config import PROMPTS

PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


class PromptError(Exception):
    pass


class Prompt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    stage: str
    version: str
    system: str | None  # the shared prompt it pairs with, `self`, or none for a shared prompt
    model: str | None
    effort: str | None
    schema_version: str | None = Field(alias="schema")
    params: list[str]
    notes: str
    body: str

    @property
    def name(self) -> str:
        return f"{self.stage}/{self.version}"

    def render(self, **values: str) -> str:
        missing = set(self.params) - set(values)
        unused = set(values) - set(self.params)
        if missing or unused:
            raise PromptError(
                f"prompt {self.name}: missing values {sorted(missing)}, unused {sorted(unused)}"
            )
        return PLACEHOLDER.sub(lambda m: values[m.group(1)], self.body)


def load(stage: str, version: str, directory: Path = PROMPTS) -> Prompt:
    path = directory / stage / f"{version}.md"
    try:
        text = path.read_text()
    except FileNotFoundError:
        raise PromptError(f"{path} not found") from None
    match = re.fullmatch(r"---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    if not match:
        raise PromptError(f"{path}: no YAML front matter between --- lines")
    try:
        prompt = Prompt.model_validate(
            {**(yaml.safe_load(match.group(1)) or {}), "body": match.group(2).strip()}
        )
    except (yaml.YAMLError, ValidationError) as e:
        raise PromptError(f"{path}: {e}") from None
    used = set(PLACEHOLDER.findall(prompt.body))
    if used != set(prompt.params):
        raise PromptError(f"{path}: params {prompt.params} but the body uses {sorted(used)}")
    if (prompt.stage, prompt.version) != (stage, version):
        raise PromptError(f"{path}: front matter says {prompt.name}")
    return prompt
