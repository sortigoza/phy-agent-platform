"""PROTOTYPE, throwaway. The one renderer of questions.yaml into prompt text, shared by Filter and Read.

Renders id, title and description, plus the scope notes. Keywords are left out: they drive
the code pre-filter, and listing them makes the model score on word overlap.
Output is deterministic (file order, no timestamps) so the cached prefix stays byte-identical.
"""

from pathlib import Path

import yaml


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def render_questions(q: dict) -> str:
    lines = []
    for item in q["questions"]:
        desc = " ".join(item["description"].split())
        lines.append(f"- {item['id']}. {item['title']}: {desc}")
    return "\n".join(lines)


def render_scope_notes(q: dict) -> str:
    return "\n".join(f"- {note}" for note in q.get("scope_notes", []))


if __name__ == "__main__":
    q = load(Path(__file__).parent / "questions.yaml")
    print(render_questions(q))
    print()
    print(render_scope_notes(q))
