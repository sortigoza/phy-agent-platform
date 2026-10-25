"""PROTOTYPE, throwaway. Card schema v1 as a proposal to react to.

Two models:
- CardDraft is what the model writes: `output_config.format` is generated from it.
  It has no loc, match_count or support: Verify owns those.
- Card is what gets stored: CardDraft plus Verify's fields. Built in verify.py.

Field order is generation order. Inside a Fact the model writes its quotes
*before* the value, so the value is written with the evidence already in hand.
Top-level order follows the review page: tl;dr, results, assumptions first.
"""

from typing import Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = "card/v1-proto"


class Quote(BaseModel):
    quote: str = Field(
        description="Copied character for character from the paper text, LaTeX included. "
        "One contiguous span of 5-60 words inside one paragraph. No ellipses."
    )


class Fact(BaseModel):
    evidence: list[Quote] = Field(min_length=1, max_length=2)
    value: str
    inferred: bool = Field(
        description="true if the value is not stated in the quotes but follows from them "
        "(combined, converted or paraphrased beyond rewording)."
    )


class Limitation(BaseModel):
    evidence: list[Quote] = Field(min_length=1, max_length=2)
    value: str


class QuestionMatch(BaseModel):
    id: Literal["Q1", "Q2", "Q3", "Q4"]
    why: str


class KeyEquation(BaseModel):
    label: str | None = Field(description="The \\label key of the equation, or null if it has none.")
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

    limitations_flagged: list[FlaggedLimitation] = Field(max_length=3)
    deep_read: DeepRead


class CardDraft(BaseModel):
    tldr: str = Field(description="Two sentences: what they did and the main result.")
    key_results: list[Fact] = Field(min_length=1, max_length=5)
    assumptions: list[Fact] = Field(max_length=4)
    system: Fact
    method: Fact
    baselines: Fact | None = Field(description="null if the paper compares against nothing.")
    claimed_advance: Fact
    limitations_stated: list[Limitation] = Field(max_length=4)
    key_equations: list[KeyEquation] = Field(max_length=3)
    key_figures: list[KeyFigure] = Field(max_length=3)
    code_data: Fact | None = Field(description="null if the paper links no code or data.")
    questions: list[QuestionMatch] = Field(max_length=4)
    opinion: Opinion


# --- stored Card: what Verify adds -------------------------------------------

Support = Literal["supported", "inferred", "unsupported"]


class VerifiedQuote(Quote):
    found: bool
    loc: str | None
    match_count: int


if __name__ == "__main__":
    import json

    from anthropic.lib._parse._transform import transform_schema

    print(json.dumps(transform_schema(CardDraft), indent=2))
