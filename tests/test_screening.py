import pytest
from pydantic import ValidationError

from phy.config import Questions
from phy.screening import scores_format, scores_model


def questions(n: int) -> Questions:
    return Questions.model_validate(
        {
            "questions": [
                {
                    "id": f"Q{i}",
                    "title": f"Question {i}",
                    "description": "A question.",
                    "keywords": [],
                    "negative_keywords": [],
                }
                for i in range(1, n + 1)
            ],
            "physics_terms": [],
            "negative_keywords": [],
            "scope_notes": [],
        }
    )


@pytest.mark.parametrize("n", [2, 5])
def test_one_field_per_question_with_reason_before_score(n):
    schema = scores_format(questions(n))["schema"]
    ids = [f"Q{i}" for i in range(1, n + 1)]
    assert list(schema["properties"]) == ids
    assert schema["required"] == ids
    assert schema["additionalProperties"] is False
    assert len({str(schema["properties"][qid]) for qid in ids}) == 1  # every question alike
    item = schema["properties"]["Q1"]
    if "$ref" in item:
        item = schema["$defs"][item["$ref"].rsplit("/", 1)[1]]
    assert list(item["properties"]) == ["reason", "score"]
    assert item["properties"]["score"]["type"] == "number"


def test_the_model_validates_scores_for_every_question_and_no_others():
    model = scores_model(questions(2))
    scores = model.model_validate_json(
        '{"Q1": {"reason": "Flows on the lattice.", "score": 0.9},'
        ' "Q2": {"reason": "Shared words only.", "score": 0.1}}'
    )
    assert scores.model_dump() == {
        "Q1": {"reason": "Flows on the lattice.", "score": 0.9},
        "Q2": {"reason": "Shared words only.", "score": 0.1},
    }
    with pytest.raises(ValidationError):
        model.model_validate({"Q1": {"reason": "x", "score": 0.9}})
