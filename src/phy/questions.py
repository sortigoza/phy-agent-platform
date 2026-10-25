"""The one renderer of `questions.yaml` into prompt text, shared by Filter and Read.

Only id, title and description are rendered, plus the scope notes. Keywords and physics terms
drive the code pre-filter and never reach a model: listing them makes it score on word overlap.
The output depends only on the file (its order, no timestamps), so a cached prefix that
contains it stays byte-identical.
"""

from phy.config import Questions


def render_questions(questions: Questions) -> str:
    return "\n".join(
        f"- {q.id}. {q.title}: {' '.join(q.description.split())}" for q in questions.questions
    )


def render_scope_notes(questions: Questions) -> str:
    return "\n".join(f"- {note}" for note in questions.scope_notes)
