"""The Verify Stage (SPEC §7.4): deterministic code checks on draft Cards.

`run()` verifies every draft Card (a catch-up, so a missed day is picked up), or with
`arxiv_id` the Card of that Paper's latest Carded version, which `force` re-verifies.

`canonicalise(text, source_type)` is the one matching contract: it runs identically on a quote
and on `flattened.txt`, and a quote is found when canonical(quote) is a substring of
canonical(source). It is a single pass that records the raw offset of every canonical character,
so `loc` maps a match back to the raw text through the same code path that found it.
"""

import bisect
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import structlog
from pydantic import ValidationError

from phy import db
from phy.card import (
    Card,
    CardDraft,
    Fact,
    Limitation,
    Quote,
    Support,
    VerifiedFact,
    VerifiedLimitation,
    VerifiedQuote,
)
from phy.ctx import Ctx

log = structlog.get_logger()

SourceType = Literal["latex", "pdf"]

_QUOTES = {"dquote": '"', "squote": "'", "dash": "-", "space": " "}
LATEX_TOKEN = re.compile(
    r"""
      (?P<drop>~?\\(?:cite[pt]?|ref|eqref|label)\*?(?:\[[^\]]*\])*\{[^{}]*\})
    | (?P<verbatim>\\\\|\\[{}])
    | \\(?P<special>[%&$])
    | (?P<unwrap>\\(?:emph|textit|textbf|text)\s*\{)
    | (?P<open>\{)
    | (?P<close>\})
    | (?P<dquote>``|''|[“”„])
    | (?P<squote>[`‘’])
    | (?P<dash>---|--|[‐-―−])
    | (?P<space>~|\\[,; \n]|\s)
    """,
    re.X,
)
# The PDF rules of SPEC §7.3 (already applied to `flattened.txt`, applied again to quotes),
# plus the shared quote, dash and whitespace rules.
PDF_TOKEN = re.compile(
    r"""
      (?P<drop>[\u0002￾­]\n?|(?<=\w)-\n(?=\w))
    | (?P<dquote>[“”„])
    | (?P<squote>[‘’])
    | (?P<dash>[‐-―−])
    | (?P<space>\s)
    """,
    re.X,
)


def canonicalise(text: str, source_type: SourceType) -> str:
    return canonicalise_mapped(text, source_type)[0]


def canonicalise_mapped(text: str, source_type: SourceType) -> tuple[str, list[int]]:
    """The canonical text and, for each of its characters, the offset in `text` it came from."""
    out: list[str] = []
    offsets: list[int] = []

    def emit(chars: str, at: int) -> None:
        for char in chars:
            if char == " " and (not out or out[-1] == " "):
                continue
            out.append(char)
            offsets.append(at)

    def emit_plain(start: int, end: int) -> None:
        for i in range(start, end):
            char = text[i]
            emit(unicodedata.normalize("NFKC", char) if pdf and ord(char) > 127 else char, i)

    pdf = source_type == "pdf"
    unwrapped: list[bool] = []  # one entry per open brace: is its closing brace dropped?
    pos = 0
    for m in (PDF_TOKEN if pdf else LATEX_TOKEN).finditer(text):
        emit_plain(pos, m.start())
        pos = m.end()
        kind = m.lastgroup
        if kind in _QUOTES:
            emit(_QUOTES[kind], m.start())
        elif kind == "verbatim":
            emit(m.group(), m.start())
        elif kind == "special":
            emit(m.group("special"), m.start())
        elif kind == "unwrap":
            unwrapped.append(True)
        elif kind == "open":
            unwrapped.append(False)
            emit("{", m.start())
        elif kind == "close" and not (unwrapped and unwrapped.pop()):
            emit("}", m.start())
    emit_plain(pos, len(text))
    if out and out[-1] == " ":
        out.pop()
        offsets.pop()
    return "".join(out), offsets


class NoCard(Exception):
    """`verify --paper` named a Paper that has no Card."""


@dataclass
class Ran:
    verified: list[int]  # card ids
    failed: list[str]  # "<arxiv_id>v<n>: <error>"


@dataclass
class AlreadyVerified:
    arxiv_id: str
    version: int
    card_id: int


def run(ctx: Ctx, arxiv_id: str | None = None, *, force: bool = False) -> Ran | AlreadyVerified:
    with structlog.contextvars.bound_contextvars(run_id=ctx.run_id, stage="verify"):
        started_at = datetime.now(UTC).isoformat(timespec="seconds")
        try:
            outcome = _verify(ctx, arxiv_id, force)
        except Exception as e:
            db.record_run(ctx.db, ctx.run_id, "verify", "failed", started_at, str(e), arxiv_id)
            raise
        if isinstance(outcome, AlreadyVerified):
            return outcome
        error = "; ".join(outcome.failed) or None
        status = "failed" if outcome.failed else "ok"
        db.record_run(ctx.db, ctx.run_id, "verify", status, started_at, error, arxiv_id)
        log.info("verify.finished", verified=len(outcome.verified), failed=len(outcome.failed))
    return outcome


def _verify(ctx: Ctx, arxiv_id: str | None, force: bool) -> Ran | AlreadyVerified:
    if arxiv_id is None:
        cards = db.draft_cards(ctx.db)
    else:
        card = db.latest_card(ctx.db, arxiv_id)
        if card is None:
            raise NoCard(f"{arxiv_id} has no Card; run phy read --paper {arxiv_id} first")
        if card["status"] != "draft" and not force:
            log.info("verify.skipped", reason="already_verified", card_id=card["id"])
            return AlreadyVerified(arxiv_id=arxiv_id, version=card["version"], card_id=card["id"])
        cards = [card]
    outcome = Ran(verified=[], failed=[])
    for card in cards:
        with structlog.contextvars.bound_contextvars(
            arxiv_id=card["arxiv_id"], version=card["version"], card_id=card["id"]
        ):
            try:
                _verify_one(ctx, card)
            except (OSError, ValidationError) as e:
                error = _describe(e)
                log.error("verify.card_failed", error=error)
                outcome.failed.append(f"{card['arxiv_id']}v{card['version']}: {error}")
            else:
                outcome.verified.append(card["id"])
    return outcome


def _describe(e: OSError | ValidationError) -> str:
    """The error without the Card text a ValidationError would echo (quotes are never logged)."""
    if isinstance(e, ValidationError):
        fields = ", ".join(".".join(map(str, err["loc"])) for err in e.errors()[:3])
        return f"card_json does not validate ({e.error_count()} errors: {fields})"
    return str(e)


def _verify_one(ctx: Ctx, card: sqlite3.Row) -> None:
    # A verified Card's JSON parses as its draft: the fields Verify added are ignored.
    draft = CardDraft.model_validate_json(card["card_json"])
    text = ctx.paths.flattened(card["arxiv_id"], card["version"]).read_text()
    verified = verify_card(draft, Source(text, card["source_type"]))
    db.write_verified_card(
        ctx.db,
        card["id"],
        verified.card.model_dump_json(),
        unsupported_count=verified.unsupported_count,
        inferred_count=verified.inferred_count,
    )
    log.info(
        "verify.card_verified",
        unsupported=verified.unsupported_count,
        inferred=verified.inferred_count,
        fields=len(facts(verified.card)),
    )


MIN_WORDS, MAX_WORDS = 5, 60
ELLIPSES = ("...", "…")
BLANK_LINE = re.compile(r"\n[ \t]*\n")
HEADINGS = ["section", "subsection", "subsubsection", "paragraph"]
LABELLED_ENVS = ["equation", "align", "gather", "multline", "eqnarray", "figure", "table"]
DEFINITION = re.compile(
    r"\\(?:(?:re|provide)?newcommand\*?|DeclareRobustCommand)\s*\{?\\(\w+)\}?|\\def\\(\w+)"
)
LET = re.compile(r"\\let\s*\\(\w+)\s*=?\s*\\(\w+)")
MACRO_ARGUMENT = re.compile(r"#\d")
ENV = re.compile(r"\\(begin|end)\{(\w+)\*?\}")
LABEL = re.compile(r"\\label\{([^{}]*)\}")


@dataclass(frozen=True)
class QuoteCheck:
    found: bool
    loc: str | None
    match_count: int


@dataclass(frozen=True)
class _Heading:
    at: int
    title: str
    appendix: bool


@dataclass(frozen=True)
class _Env:
    """A labelled environment: its raw span and every `\\label` in it, with offsets."""

    start: int
    end: int
    labels: list[tuple[int, str]]

    def label_for(self, at: int) -> str:
        """The label of the row or caption holding `at`: a label ends its `align` row and
        follows its caption, so the first label after `at`, else the last one."""
        return next((key for pos, key in self.labels if pos >= at), self.labels[-1][1])


class Source:
    """A paper's `flattened.txt`, canonicalised once, that quotes are checked against."""

    def __init__(self, raw: str, source_type: SourceType):
        self.raw = raw
        self.source_type = source_type
        self.text, self.offsets = canonicalise_mapped(raw, source_type)
        boundaries = [m.start() for m in BLANK_LINE.finditer(raw)]
        self.headings: list[_Heading] = []
        self.abstracts: list[tuple[int, int]] = []
        self.envs: list[_Env] = []
        if source_type == "latex":
            self.headings = _headings(raw)
            boundaries += [h.at for h in self.headings]
            boundaries += [m.start() for m in re.finditer(r"\\appendix(?![a-zA-Z])", raw)]
            self.abstracts = _envs(raw, ["abstract"])
            self.envs = [
                _Env(start, end, labels)
                for start, end in _envs(raw, LABELLED_ENVS)
                if (labels := [(m.start(), m.group(1)) for m in LABEL.finditer(raw, start, end)])
            ]
        self.boundaries = sorted(boundaries)

    def check(self, quote: str) -> QuoteCheck:
        """Found when the canonical quote is in the canonical source, has the right shape, and
        some match does not cross a paragraph or section boundary. `loc` is read off the first
        such match (or the first match, when every one crosses)."""
        canonical = canonicalise(quote, self.source_type)
        if not canonical:
            return QuoteCheck(found=False, loc=None, match_count=0)
        spans = []
        start = self.text.find(canonical)
        while start != -1:
            spans.append((self.offsets[start], self.offsets[start + len(canonical) - 1]))
            start = self.text.find(canonical, start + 1)
        if not spans:
            return QuoteCheck(found=False, loc=None, match_count=0)
        clean = next((span for span in spans if not self._crosses(span)), None)
        words = len(canonical.split())
        shaped = MIN_WORDS <= words <= MAX_WORDS and not any(e in quote for e in ELLIPSES)
        return QuoteCheck(
            found=shaped and clean is not None,
            loc=self.loc((clean or spans[0])[0]),
            match_count=len(spans),
        )

    def _crosses(self, span: tuple[int, int]) -> bool:
        i = bisect.bisect_left(self.boundaries, span[0])
        return i < len(self.boundaries) and self.boundaries[i] < span[1]

    def loc(self, at: int) -> str:
        """Where a raw offset sits: `p. N` for a PDF; for LaTeX the innermost heading (or
        Abstract, or front matter) plus the label of the innermost labelled environment."""
        if self.source_type == "pdf":
            return f"p. {self.raw.count(chr(12), 0, at) + 1}"
        if any(start <= at < end for start, end in self.abstracts):
            where = "Abstract"
        else:
            i = bisect.bisect_right([h.at for h in self.headings], at)
            if i == 0:
                where = "front matter"
            else:
                heading = self.headings[i - 1]
                where = f'{"App." if heading.appendix else "Sec."} "{heading.title}"'
        enclosing = [env for env in self.envs if env.start <= at < env.end]
        if enclosing:
            where += f" · {max(enclosing, key=lambda env: env.start).label_for(at)}"
        return where


@dataclass(frozen=True)
class Verified:
    card: Card
    unsupported_count: int
    inferred_count: int


def verify_card(draft: CardDraft, source: Source) -> Verified:
    """Check every quote on every Fact and set Support from it: a Fact is `unsupported` unless
    it has Evidence and every quote is found, and otherwise `inferred` when the model said so."""

    def evidence(quotes: list[Quote]) -> tuple[list[VerifiedQuote], bool]:
        checked = [VerifiedQuote(quote=q.quote, **vars(source.check(q.quote))) for q in quotes]
        return checked, bool(checked) and all(q.found for q in checked)

    def fact(f: Fact | None) -> VerifiedFact | None:
        if f is None:
            return None
        checked, grounded = evidence(f.evidence)
        support: Support = (
            "unsupported" if not grounded else "inferred" if f.inferred else "supported"
        )
        return VerifiedFact(
            evidence=checked,
            value=f.value,
            inferred=f.inferred,
            support=support,
            ungrounded_numbers=[],
        )

    def limitation(f: Limitation) -> VerifiedLimitation:
        checked, grounded = evidence(f.evidence)
        return VerifiedLimitation(
            evidence=checked, value=f.value, support="supported" if grounded else "unsupported"
        )

    card = Card.model_validate(
        {
            **draft.model_dump(),
            "key_results": [fact(f) for f in draft.key_results],
            "assumptions": [fact(f) for f in draft.assumptions],
            "system": fact(draft.system),
            "method": fact(draft.method),
            "baselines": fact(draft.baselines),
            "claimed_advance": fact(draft.claimed_advance),
            "limitations_stated": [limitation(f) for f in draft.limitations_stated],
            "code_data": fact(draft.code_data),
        }
    )
    supports = [f.support for f in facts(card)]
    return Verified(
        card=card,
        unsupported_count=supports.count("unsupported"),
        inferred_count=supports.count("inferred"),
    )


def facts(card: Card) -> list[VerifiedFact | VerifiedLimitation]:
    """Every field that has Support, in Card order."""
    singles = [card.system, card.method, card.baselines, card.claimed_advance, card.code_data]
    return [
        *card.key_results,
        *card.assumptions,
        *[f for f in singles if f is not None],
        *card.limitations_stated,
    ]


def _headings(raw: str) -> list[_Heading]:
    """Every heading in the document body, with its raw title (labels removed). Heading
    commands are the standard ones plus macros defined (or `\\let`) in the preamble whose name
    or body contains `section`. Without `\\begin{document}` (a bare fragment) the whole text is
    both, and a heading inside a macro body (titled `#1`) is skipped."""
    body = raw.find("\\begin{document}")
    preamble_end = len(raw) if body == -1 else body
    body = max(body, 0)
    names = set(HEADINGS)
    for m in DEFINITION.finditer(raw, 0, preamble_end):
        name = m.group(1) or m.group(2)
        definition = _braced(raw, raw.find("{", m.end()))
        if "section" in name or (definition and "section" in definition[0]):
            names.add(name)
    for m in LET.finditer(raw, 0, preamble_end):
        if "section" in m.group(1) or "section" in m.group(2):
            names.add(m.group(1))
    command = re.compile(
        r"\\("
        + "|".join(sorted(names, key=len, reverse=True))
        + r")(?![a-zA-Z])\*?\s*(?:\[[^\]]*\]\s*)?(?=\{)"
    )
    appendix = re.search(r"\\appendix(?![a-zA-Z])", raw[body:])
    appendix_at = body + appendix.start() if appendix else len(raw)
    headings = []
    for m in command.finditer(raw, body):
        title = _braced(raw, m.end())
        if title and not MACRO_ARGUMENT.search(title[0]):
            headings.append(
                _Heading(
                    at=m.start(),
                    title=LABEL.sub("", title[0]).strip(),
                    appendix=m.start() > appendix_at,
                )
            )
    return headings


def _braced(raw: str, at: int) -> tuple[str, int] | None:
    """The content of the balanced `{…}` group opening at `at`, and the offset after it."""
    if at < 0 or at >= len(raw) or raw[at] != "{":
        return None
    depth = 0
    i = at
    while i < len(raw):
        char = raw[i]
        if char == "\\":
            i += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return raw[at + 1 : i], i + 1
        i += 1
    return None


def _envs(raw: str, names: list[str]) -> list[tuple[int, int]]:
    """(start, end) of every environment with one of these names, starred too, nesting allowed."""
    spans = []
    open_: list[tuple[str, int]] = []
    for m in ENV.finditer(raw):
        kind, name = m.group(1), m.group(2)
        if name not in names:
            continue
        if kind == "begin":
            open_.append((name, m.start()))
        elif open_ and open_[-1][0] == name:
            spans.append((open_.pop()[1], m.end()))
    return spans
