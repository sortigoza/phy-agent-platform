"""The `/review` page's view of one Card (SPEC §9): every reviewable field in Card order, grouped
into the sections the section pills jump between, with what Verify found attached.
"""

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Literal

from phy.card import Card, VerifiedFact, VerifiedLimitation
from phy.config import Paths
from phy.ui.figures import figure_index, renderable, resolve
from phy.ui.latex import preamble_macros, tex_html

SUMMARY, SETUP, LIMITATIONS, EQUATIONS, OPINION = (
    "Summary",
    "Setup",
    "Limitations",
    "Equations & figures",
    "Agent's opinion",
)
# The section of each top-level Card field, for its rows and its Verify warnings.
SECTION = {
    "tldr": SUMMARY,
    "key_results": SUMMARY,
    "assumptions": SUMMARY,
    "system": SETUP,
    "method": SETUP,
    "baselines": SETUP,
    "claimed_advance": SETUP,
    "code_data": SETUP,
    "limitations_stated": LIMITATIONS,
    "key_equations": EQUATIONS,
    "key_figures": EQUATIONS,
    "questions": EQUATIONS,
    "opinion": OPINION,
}
# The kinds of Flag, as `flags.kind`, with their labels; the form's keys 1–4 follow this order.
FLAG_KINDS = {
    "wrong_value": "Wrong value",
    "quote_doesnt_support": "Quote doesn't support it",
    "missing": "Missing",
    "should_be_opinion": "Should be opinion",
}
SETUP_FIELDS = [
    ("system", "System"),
    ("method", "Method"),
    ("baselines", "Baselines"),
    ("claimed_advance", "Claimed advance"),
    ("code_data", "Code / data"),
]


@dataclass(frozen=True)
class QuoteView:
    raw: str
    html: str
    found: bool
    loc: str | None
    also: int  # matches beyond the first


@dataclass(frozen=True)
class FigureFile:
    name: str
    state: Literal["ok", "not_renderable", "missing"]


@dataclass
class Field:
    path: str  # the Flag target, as in `flags.field_path`
    label: str
    kind: Literal["text", "fact", "none", "equation", "figure", "opinion"]
    value_html: str
    text: str  # the value as the Card holds it, for the Markdown export
    support: str | None = None
    quotes: list[QuoteView] = field(default_factory=list)
    numbers: list[tuple[str, Literal["quote", "paper"]]] = field(default_factory=list)
    latex: str = ""
    caption_html: str = ""
    files: list[FigureFile] = field(default_factory=list)


@dataclass
class Section:
    name: str
    fields: list[Field] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)  # {kind, field, detail}

    @property
    def unsupported(self) -> int:
        return sum(f.support == "unsupported" for f in self.fields)


@dataclass
class ReviewView:
    row: sqlite3.Row  # the Card row from `db.review_queue`
    card: Card
    sections: list[Section]
    counts: dict[str, int]  # fields per Support
    invented: int
    macros: dict[str, str]
    stale_note: str | None


def view(paths: Paths, row: sqlite3.Row) -> ReviewView:
    card = Card.model_validate_json(row["card_json"])
    flattened = paths.flattened(row["arxiv_id"], row["version"])
    tex = flattened.read_text() if flattened.is_file() else ""
    invented = json.loads(row["invented_numbers_json"] or "[]")
    sections = {name: Section(name) for name in dict.fromkeys(SECTION.values())}
    for f in _fields(paths, row, card, tex, invented):
        sections[_section(f.path)].fields.append(f)
    for w in json.loads(row["warnings_json"] or "[]"):
        sections[_section(w["field"])].warnings.append(w)
    supports = [f.support for s in sections.values() for f in s.fields]
    stale = row["status"] == "stale"
    return ReviewView(
        row=row,
        card=card,
        sections=list(sections.values()),
        counts={s: supports.count(s) for s in ("supported", "inferred", "unsupported")},
        invented=len(invented),
        macros=preamble_macros(tex) if row["source_type"] != "pdf" else {},
        stale_note=(
            f"v{row['latest_version']} has arrived; this Card is from v{row['version']}"
            if stale
            else None
        ),
    )


def _section(path: str) -> str:
    """The section of a field path such as `key_results[0].evidence` or `opinion.deep_read`."""
    return SECTION[path.split("[")[0].split(".")[0]]


def _fields(
    paths: Paths, row: sqlite3.Row, card: Card, tex: str, invented: list[dict]
) -> list[Field]:
    def numbers(path: str, ungrounded: list[str]) -> list[tuple[str, str]]:
        found = [(n, "quote") for n in ungrounded]
        return found + [(n["number"], "paper") for n in invented if n["field"] == path]

    def fact(path: str, label: str, f: VerifiedFact | VerifiedLimitation | None) -> Field:
        if f is None:
            return Field(path, label, "none", "<em>none</em>", "none")
        return Field(
            path,
            label,
            "fact",
            tex_html(f.value),
            f.value,
            support=f.support,
            quotes=[
                QuoteView(q.quote, tex_html(q.quote), q.found, q.loc, max(q.match_count - 1, 0))
                for q in f.evidence
            ],
            numbers=numbers(path, f.ungrounded_numbers),
        )

    fields = [
        Field("tldr", "tl;dr", "text", tex_html(card.tldr), card.tldr, numbers=numbers("tldr", []))
    ]
    fields += [
        fact(f"key_results[{i}]", f"Result {i + 1}", f) for i, f in enumerate(card.key_results)
    ]
    fields += [
        fact(f"assumptions[{i}]", f"Assumption {i + 1}", f) for i, f in enumerate(card.assumptions)
    ]
    fields += [fact(name, label, getattr(card, name)) for name, label in SETUP_FIELDS]
    fields += [
        fact(f"limitations_stated[{i}]", f"Stated limitation {i + 1}", f)
        for i, f in enumerate(card.limitations_stated)
    ]
    for i, e in enumerate(card.key_equations):
        fields.append(
            Field(
                f"key_equations[{i}]",
                f"Equation {e.label or i + 1}",
                "equation",
                tex_html(e.meaning),
                e.meaning,
                latex=e.latex,
            )
        )
    index = figure_index(tex)
    for i, kf in enumerate(card.key_figures):
        env = index.get(kf.label)
        fields.append(
            Field(
                f"key_figures[{i}]",
                f"Figure {kf.label}",
                "figure",
                tex_html(kf.why),
                kf.why,
                caption_html=tex_html(env.caption) if env else "",
                files=[_figure_file(paths, row, name) for name in env.files] if env else [],
            )
        )
    questions = ", ".join(f"<b>{q.id}</b>: {tex_html(q.why)}" for q in card.questions)
    fields.append(
        Field(
            "questions",
            "Research questions",
            "text",
            questions or "<em>none</em>",
            "; ".join(f"{q.id}: {q.why}" for q in card.questions) or "none",
        )
    )
    for i, lf in enumerate(card.opinion.limitations_flagged):
        fields.append(
            Field(
                f"opinion.limitations_flagged[{i}]",
                f"Flagged limitation {i + 1}",
                "opinion",
                tex_html(lf.value),
                lf.value,
            )
        )
    deep_read = card.opinion.deep_read
    verdict = "Recommend" if deep_read.recommend else "Skip"
    fields.append(
        Field(
            "opinion.deep_read",
            "Deep read?",
            "opinion",
            f"<b>{verdict}</b> — {tex_html(deep_read.why)}",
            f"{verdict} — {deep_read.why}",
        )
    )
    return fields


def _figure_file(paths: Paths, row: sqlite3.Row, name: str) -> FigureFile:
    path = resolve(paths, row["arxiv_id"], row["version"], name)
    if path is None:
        return FigureFile(name, "missing")
    return FigureFile(name, "ok" if renderable(path) else "not_renderable")
