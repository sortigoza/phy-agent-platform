"""`/review`'s "Export to Markdown": a Card as the page shows it, in Card order, with what
Verify found, the Flags and the Review. Values stay raw LaTeX.
"""

import sqlite3

from phy.ui.review import FLAG_KINDS, Field, ReviewView


def markdown(v: ReviewView, flags: list[sqlite3.Row], review: sqlite3.Row | None) -> str:
    row = v.row
    paper = f"{row['arxiv_id']}v{row['version']}"
    counts = ", ".join(f"{n} {support}" for support, n in v.counts.items())
    lines = [
        f"# {row['title']}",
        "",
        f"[arXiv:{paper}](https://arxiv.org/abs/{paper}) · {row['authors']}",
        "",
        f"Card {row['id']} ({row['status']}): {counts}, {v.invented} invented numbers;"
        f" model {row['model']}, prompt {row['prompt_version']}, schema {row['schema_version']}.",
    ]
    if v.stale_note:
        lines += ["", f"Stale: {v.stale_note}."]
    by_path: dict[str, list[sqlite3.Row]] = {}
    for f in flags:
        by_path.setdefault(f["field_path"], []).append(f)
    for section in v.sections:
        lines += ["", f"## {section.name}"]
        lines += [f"- Verify warning: {w['field']}: {w['detail']}" for w in section.warnings]
        for f in section.fields:
            lines += ["", *_field(f, by_path.get(f.path, []))]
    lines += ["", "## Review", ""]
    if review is None:
        lines.append("Not reviewed yet.")
    else:
        seconds = review["seconds_spent"] or 0
        lines += [
            f"- Relevance: {review['relevance']}",
            f"- Deep read: {'yes' if review['deep_read'] else 'no'}",
            f"- Time: {seconds // 60}:{seconds % 60:02d}",
            f"- Reviewed at: {review['created_at']}",
        ]
        if review["note"]:
            lines.append(f"- Note: {review['note']}")
    return "\n".join(lines) + "\n"


def _field(f: Field, flags: list[sqlite3.Row]) -> list[str]:
    marks = [f.support] if f.support in ("inferred", "unsupported") else []
    marks += [f"{n} ∉ {where}" for n, where in f.numbers]
    head = f"**{f.label}**" + (f" ({', '.join(marks)})" if marks else "")
    lines = [f"{head}: {f.text}"]
    if f.latex:
        lines += ["", f"$$ {f.latex} $$"]
    for q in f.quotes:
        where = q.loc if q.found else "not found in the paper"
        also = f", also appears {q.also}× elsewhere" if q.also else ""
        lines += ["", f"> {q.raw}", f"> — {where}{also}"]
    for file in f.files:
        if file.state != "ok":
            lines += ["", f"- {file.name}: {file.state.replace('_', ' ')}"]
    for fl in flags:
        note = f": {fl['note']}" if fl["note"] else ""
        lines += ["", f"- ⚑ {FLAG_KINDS[fl['kind']]}{note}"]
    return lines
