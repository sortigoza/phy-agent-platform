from importlib.resources import files

import yaml

from phy.config import Questions
from phy.questions import render_questions, render_scope_notes

DEFAULT = Questions.model_validate(
    yaml.safe_load((files("phy") / "defaults" / "questions.yaml").read_text())
)


def test_questions_render_as_one_line_each_with_id_title_and_description():
    lines = render_questions(DEFAULT).splitlines()
    assert len(lines) == 4
    assert lines[1] == (
        "- Q2. Neural quantum states: Which neural-network wavefunction architectures reach"
        " state-of-the-art ground-state energies or dynamics, compared with DMRG, tensor networks"
        " and QMC?"
    )


def test_rendering_is_byte_identical_across_calls():
    assert render_questions(DEFAULT) == render_questions(DEFAULT)
    assert render_scope_notes(DEFAULT) == render_scope_notes(DEFAULT)


def test_keywords_never_reach_the_prompt():
    text = render_questions(DEFAULT) + render_scope_notes(DEFAULT)
    for word in [
        "restricted Boltzmann machine",
        "ansatz",
        "order parameter",
        "neural-network quantum state",
        "superconducting qubit fabrication",
    ]:
        assert word not in text
    assert "Hamiltonian" not in text  # physics_terms are pre-filter only too


def test_scope_notes_render_as_a_list():
    assert render_scope_notes(DEFAULT).splitlines()[1] == (
        "- Quantum-computing hardware, devices or benchmarks of quantum processors."
    )
