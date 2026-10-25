"""The Filter call's output: one `{reason, score}` per question id in `questions.yaml`.

The model is built from the ids, so adding a question changes no code (it does change the
cached prefix and the `scores_json` keys; old screenings keep theirs). `reason` comes before
`score`, as quotes come before the value in a Card.
"""

from anthropic.lib._parse._transform import transform_schema
from pydantic import BaseModel, ConfigDict, Field, create_model

from phy.config import Questions

SCHEMA_VERSION = "filter/v1"


class Score(BaseModel):
    reason: str = Field(description="One line, at most 20 words.")
    score: float = Field(description="0 to 1.")


def scores_model(questions: Questions) -> type[BaseModel]:
    return create_model(
        "FilterScores",
        __config__=ConfigDict(extra="forbid"),
        **{q.id: (Score, ...) for q in questions.questions},
    )


def scores_format(questions: Questions) -> dict:
    """`output_config.format` for a Filter call: the schema exactly as the SDK sends it."""
    return {"type": "json_schema", "schema": transform_schema(scores_model(questions))}
