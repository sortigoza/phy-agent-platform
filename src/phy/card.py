"""The Card schema: `CardDraft` is what the model writes, `Card` is what is stored.

`CardDraft` is the single source for the API's `output_config.format` and for validating the
response. Field order is generation order, and inside a Fact the quotes come before the value.
List caps live in the prompt and the field descriptions, not in the schema: the API ignores
`maxItems` and a paid call should not fail over one extra item, so Verify trims instead.
`Card` adds what Verify fills in: Support, `loc`, `match_count` and `ungrounded_numbers`.
"""

import json
from pathlib import Path
from typing import Literal

from anthropic.lib._parse._transform import transform_schema
from pydantic import BaseModel, Field

SCHEMA_VERSION = "card/v1"


class Quote(BaseModel):
    quote: str = Field(
        description="Copied character for character from the paper text, LaTeX included. "
        "One contiguous span of 5-60 words inside one paragraph. No ellipses."
    )


class Fact(BaseModel):
    evidence: list[Quote] = Field(min_length=1, description="1 or 2 quotes.")
    value: str
    inferred: bool = Field(
        description="true if the value is not stated in the quotes but follows from them "
        "(combined, converted or paraphrased beyond rewording)."
    )


class Limitation(BaseModel):
    evidence: list[Quote] = Field(min_length=1, description="1 or 2 quotes.")
    value: str


class QuestionMatch(BaseModel):
    id: str = Field(description="A research question id, such as Q1.")
    why: str


class KeyEquation(BaseModel):
    label: str | None = Field(
        description="The \\label key of the equation, or null if it has none."
    )
    latex: str = Field(description="The equation body copied from the source.")
    meaning: str


class KeyFigure(BaseModel):
    label: str = Field(description="The \\label key of the figure environment.")
    why: str


class FlaggedLimitation(BaseModel):
    value: str


class DeepRead(BaseModel):
    recommend: bool
    why: str


class Opinion(BaseModel):
    """The agent's own judgement, never the paper's claims."""

    limitations_flagged: list[FlaggedLimitation] = Field(description="At most 3.")
    deep_read: DeepRead


class CardDraft(BaseModel):
    tldr: str = Field(description="Two sentences: what they did and the main result.")
    key_results: list[Fact] = Field(min_length=1, description="1 to 5, most important first.")
    assumptions: list[Fact] = Field(description="At most 4.")
    system: Fact
    method: Fact
    baselines: Fact | None = Field(description="null if the paper compares against nothing.")
    claimed_advance: Fact
    limitations_stated: list[Limitation] = Field(description="At most 4.")
    key_equations: list[KeyEquation] = Field(description="At most 3.")
    key_figures: list[KeyFigure] = Field(description="At most 3.")
    code_data: Fact | None = Field(description="null if the paper links no code or data.")
    questions: list[QuestionMatch] = Field(description="At most 4.")
    opinion: Opinion


Support = Literal["supported", "inferred", "unsupported"]


class VerifiedQuote(Quote):
    found: bool
    loc: str | None
    match_count: int


class VerifiedFact(Fact):
    evidence: list[VerifiedQuote]
    support: Support
    ungrounded_numbers: list[str]


class VerifiedLimitation(Limitation):
    evidence: list[VerifiedQuote]
    support: Support


class Card(CardDraft):
    key_results: list[VerifiedFact]
    assumptions: list[VerifiedFact]
    system: VerifiedFact
    method: VerifiedFact
    baselines: VerifiedFact | None
    claimed_advance: VerifiedFact
    limitations_stated: list[VerifiedLimitation]
    code_data: VerifiedFact | None


def draft_format() -> dict:
    """`output_config.format` for a Read call: the schema exactly as the SDK sends it."""
    return {"type": "json_schema", "schema": transform_schema(CardDraft)}


def schemas() -> dict[str, dict]:
    return {"card_draft": draft_format()["schema"], "card": Card.model_json_schema()}


def export_schemas(directory: Path) -> list[Path]:
    """Write `schemas/<name>.json`, so schema changes show up in diffs."""
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for name, schema in schemas().items():
        path = directory / f"{name}.json"
        path.write_text(json.dumps(schema, indent=2) + "\n")
        written.append(path)
    return written
