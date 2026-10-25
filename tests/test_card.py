import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from phy.card import Card, CardDraft, export_schemas, schemas

FIXTURES = Path(__file__).parent / "fixtures" / "anthropic"
REPO_SCHEMAS = Path(__file__).parents[1] / "schemas"


def fact(value="L=16..64", inferred=False):
    return {
        "evidence": [{"quote": "We study lattices of size L=16 to L=64."}],
        "value": value,
        "inferred": inferred,
    }


def draft(**overrides):
    return {
        "tldr": "They train a flow. It decorrelates faster.",
        "key_results": [fact("tau reduced 10x")],
        "assumptions": [],
        "system": fact(),
        "method": fact("Normalizing flow proposals", inferred=True),
        "baselines": None,
        "claimed_advance": fact("Faster sampling"),
        "limitations_stated": [
            {"evidence": [{"quote": "We only study two dimensions here."}], "value": "2D only"}
        ],
        "key_equations": [{"label": None, "latex": "Z = \\int D\\phi", "meaning": "Partition"}],
        "key_figures": [{"label": "fig:tau", "why": "Shows the speedup"}],
        "code_data": None,
        "questions": [{"id": "Q1", "why": "Generative sampling"}],
        "opinion": {
            "limitations_flagged": [{"value": "Small volumes"}],
            "deep_read": {"recommend": False, "why": "Incremental"},
        },
        **overrides,
    }


def test_a_hand_written_draft_parses():
    card = CardDraft.model_validate(draft())
    assert card.method.inferred is True
    assert card.baselines is None
    assert card.opinion.deep_read.recommend is False


def test_the_recorded_read_response_parses_as_a_draft():
    response = json.loads((FIXTURES / "read_1904.12072v3_response.json").read_text())
    card = CardDraft.model_validate_json(response["content"][0]["text"])
    assert len(card.key_results) >= 1


@pytest.mark.parametrize(
    "broken",
    [
        {"key_results": []},
        {"system": {"evidence": [], "value": "x", "inferred": False}},
    ],
)
def test_evidence_and_key_results_must_not_be_empty(broken):
    with pytest.raises(ValidationError):
        CardDraft.model_validate(draft(**broken))


def test_list_caps_are_soft_so_an_extra_item_still_parses():
    card = CardDraft.model_validate(draft(key_results=[fact(str(i)) for i in range(7)]))
    assert len(card.key_results) == 7


def test_quotes_come_before_the_value_in_the_draft_schema():
    defs = schemas()["card_draft"]["$defs"]
    assert list(defs["Fact"]["properties"]) == ["evidence", "value", "inferred"]
    assert list(defs["Limitation"]["properties"]) == ["evidence", "value"]


def test_the_draft_schema_has_one_opinion_block_and_nullable_baselines():
    schema = schemas()["card_draft"]
    assert list(schema["properties"])[-1] == "opinion"
    assert schema["properties"]["baselines"]["anyOf"][1] == {"type": "null"}
    assert schema["properties"]["code_data"]["anyOf"][1] == {"type": "null"}


def test_a_stored_card_adds_the_verify_fields():
    stored = draft()
    for name in ["system", "method", "claimed_advance"]:
        stored[name] = {**stored[name], "support": "supported", "ungrounded_numbers": []}
        stored[name]["evidence"] = [
            {**q, "found": True, "loc": 'Sec. "Setup"', "match_count": 1}
            for q in stored[name]["evidence"]
        ]
    stored["key_results"] = [
        {
            **fact("tau reduced 10x"),
            "support": "inferred",
            "ungrounded_numbers": ["10"],
            "evidence": [{"quote": "q" * 30, "found": True, "loc": "Abstract", "match_count": 2}],
        }
    ]
    stored["limitations_stated"] = [
        {
            "value": "2D only",
            "support": "unsupported",
            "ungrounded_numbers": [],
            "evidence": [{"quote": "q" * 30, "found": False, "loc": None, "match_count": 0}],
        }
    ]
    card = Card.model_validate(stored)
    assert card.key_results[0].ungrounded_numbers == ["10"]
    assert card.key_results[0].evidence[0].match_count == 2
    assert card.limitations_stated[0].support == "unsupported"

    with pytest.raises(ValidationError):
        Card.model_validate(draft())  # a draft lacks Support


def test_committed_schemas_are_up_to_date():
    for name, schema in schemas().items():
        committed = json.loads((REPO_SCHEMAS / f"{name}.json").read_text())
        assert committed == schema, f"schemas/{name}.json is stale; run `phy schema export`"


def test_export_writes_both_schemas(tmp_path):
    written = export_schemas(tmp_path)
    assert sorted(p.name for p in written) == ["card.json", "card_draft.json"]
    assert json.loads((tmp_path / "card_draft.json").read_text()) == schemas()["card_draft"]
