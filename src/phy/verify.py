"""The Verify Stage (SPEC §7.4): deterministic code checks on draft Cards.

`run()` verifies every draft Card (a catch-up, so a missed day is picked up), or with
`arxiv_id` the Card of that Paper's latest Carded version, which `force` re-verifies.

`canonicalise(text, source_type)` is the one matching contract: it runs identically on a quote
and on `flattened.txt`, and a quote is found when canonical(quote) is a substring of
canonical(source). It is a single pass that records the raw offset of every canonical character,
so `loc` maps a match back to the raw text through the same code path that found it.

`numbers(text)` is the one number extractor, run on canonical values, quotes and source alike:
numbers are compared as parsed values (decimal value plus significant figures), never as
substrings.
"""

import bisect
import json
import re
import sqlite3
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

import structlog
from pydantic import ValidationError

from phy import db
from phy.card import (
    Card,
    CardDraft,
    Fact,
    Limitation,
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


_SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")
# Digits glued to an identifier are not numbers: after a letter, digit, `_`, `^` or `\\` (also
# `^{`, `_{`), or before a letter other than an `x`/`×` multiplier. The atomic group keeps a
# rejected token from matching a shorter prefix of itself (`12D` is not `1`).
NUMBER = re.compile(
    r"""
    (?<![\w\\^])(?<!\^\{)(?<!_\{)
    (?>
      (?P<int>\d+)(?:\.(?P<frac>\d+))?
      (?:\((?P<unc>\d+)\))?
      (?:
        [eE](?P<e>[-+−]?\d+)
      | \s*(?:\\times|×)\s*10(?:\^\{?(?P<tex>[-+−]?\d+)\}?|(?P<sup>[⁻⁺]?[⁰¹²³⁴⁵⁶⁷⁸⁹]+))
      )?
    )
    (?:(?=[x×](?!\w))|(?!\w))
    """,
    re.X,
)


@dataclass(frozen=True)
class Number:
    """A parsed number: equal to another when the decimal value and significant figures match.
    `text` is the token it came from (shared by a value and its `(d)` uncertainty)."""

    value: Decimal
    sig: int
    text: str = field(compare=False)


def numbers(text: str) -> list[Number]:
    """Every number in a canonical text, in order; an error bar `4.03(6)` gives two. Signs are
    ignored, because dashes are ambiguous (`6-14`, `m^2=-4`)."""
    found = []
    for m in NUMBER.finditer(text):
        frac = m.group("frac") or ""
        exponent = m.group("e") or m.group("tex") or (m.group("sup") or "").translate(_SUPERSCRIPTS)
        exp = int(exponent.replace("−", "-")) if exponent else 0
        token = m.group().strip()
        found.append(
            Number(
                Decimal(f"{m.group('int')}.{frac}").scaleb(exp), _sig(m.group("int") + frac), token
            )
        )
        if m.group("unc"):
            unc = m.group("unc")
            found.append(Number(Decimal(unc).scaleb(exp - len(frac)), _sig(unc), token))
    return found


def _sig(digits: str) -> int:
    """Significant figures of a digit string: leading zeros don't count (`0.0012` has 2)."""
    return len(digits.lstrip("0")) or 1


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
        invented_numbers_json=json.dumps([asdict(n) for n in verified.invented_numbers]),
        warnings_json=json.dumps([asdict(w) for w in verified.warnings]),
    )
    log.info(
        "verify.card_verified",
        unsupported=verified.unsupported_count,
        inferred=verified.inferred_count,
        invented=len(verified.invented_numbers),
        warnings=len(verified.warnings),
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
    """A labelled environment: its name, raw span, body span (inside `\\begin`…`\\end`) and
    every `\\label` in it, with offsets."""

    name: str
    start: int
    end: int
    body: tuple[int, int]
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
        self.labels: set[str] = set()
        if source_type == "latex":
            self.headings = _headings(raw)
            boundaries += [h.at for h in self.headings]
            boundaries += [m.start() for m in re.finditer(r"\\appendix(?![a-zA-Z])", raw)]
            self.abstracts = [(start, end) for _, start, end, _ in _envs(raw, ["abstract"])]
            self.envs = [
                _Env(name, start, end, body, labels)
                for name, start, end, body in _envs(raw, LABELLED_ENVS)
                if (labels := [(m.start(), m.group(1)) for m in LABEL.finditer(raw, start, end)])
            ]
            self.labels = {m.group(1) for m in LABEL.finditer(raw)}
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

    def labelled(self, label: str) -> list[_Env]:
        """The labelled environments holding `\\label{label}`, outermost first."""
        return [env for env in self.envs if any(key == label for _, key in env.labels)]

    def env_body(self, env: _Env) -> str:
        return canonicalise(self.raw[env.body[0] : env.body[1]], self.source_type)


@dataclass(frozen=True)
class InventedNumber:
    """A number in `field`'s value (or the `tldr`) that the canonical source does not contain."""

    field: str
    number: str


@dataclass(frozen=True)
class CardWarning:
    """A check that failed without changing Support, shown as a grey chip on its section."""

    kind: Literal[
        "over_cap",
        "no_key_results",
        "unknown_label",
        "equation_mismatch",
        "figure_label_not_figure",
    ]
    field: str
    detail: str


@dataclass(frozen=True)
class Verified:
    card: Card
    unsupported_count: int
    inferred_count: int
    invented_numbers: list[InventedNumber]
    warnings: list[CardWarning]


def verify_card(draft: CardDraft, source: Source) -> Verified:
    """Check every quote and number on every Fact and set Support from them, with precedence
    `unsupported` > `inferred` > `supported`. A Fact is `unsupported` without Evidence, with a
    quote not found, or with a number in its value the source doesn't contain (an invented
    number); otherwise `inferred` when the model said so or a number in its value is missing
    from its own quotes (an ungrounded number)."""
    draft, warnings = _trim(draft)
    source_numbers = set(numbers(source.text))
    invented: list[InventedNumber] = []

    def numbers_in(text: str) -> list[Number]:
        return numbers(canonicalise(text, source.source_type))

    def invented_in(path: str, value: str) -> bool:
        missing = _unique(n.text for n in numbers_in(value) if n not in source_numbers)
        invented.extend(InventedNumber(path, number) for number in missing)
        return bool(missing)

    def checked(path: str, f: Fact | Limitation) -> dict:
        quotes = [VerifiedQuote(quote=q.quote, **vars(source.check(q.quote))) for q in f.evidence]
        quoted = {n for q in f.evidence for n in numbers_in(q.quote)}
        ungrounded = _unique(
            n.text for n in numbers_in(f.value) if n in source_numbers and n not in quoted
        )
        invents = invented_in(path, f.value)
        support: Support = (
            "unsupported"
            if not quotes or not all(q.found for q in quotes) or invents
            else "inferred"
            if getattr(f, "inferred", False) or ungrounded
            else "supported"
        )
        return {
            **f.model_dump(),
            "evidence": quotes,
            "support": support,
            "ungrounded_numbers": ungrounded,
        }

    def fact(path: str, f: Fact | None) -> dict | None:
        return None if f is None else checked(path, f)

    invented_in("tldr", draft.tldr)
    warnings += _label_warnings(draft, source)
    card = Card.model_validate(
        {
            **draft.model_dump(),
            "key_results": [fact(f"key_results[{i}]", f) for i, f in enumerate(draft.key_results)],
            "assumptions": [fact(f"assumptions[{i}]", f) for i, f in enumerate(draft.assumptions)],
            "system": fact("system", draft.system),
            "method": fact("method", draft.method),
            "baselines": fact("baselines", draft.baselines),
            "claimed_advance": fact("claimed_advance", draft.claimed_advance),
            "limitations_stated": [
                checked(f"limitations_stated[{i}]", f)
                for i, f in enumerate(draft.limitations_stated)
            ],
            "code_data": fact("code_data", draft.code_data),
        }
    )
    supports = [f.support for f in facts(card)]
    return Verified(
        card=card,
        unsupported_count=supports.count("unsupported"),
        inferred_count=supports.count("inferred"),
        invented_numbers=invented,
        warnings=warnings,
    )


# The list caps the Read prompt states (SPEC §7.3); the schema doesn't enforce them.
CAPS = {
    "key_results": 5,
    "assumptions": 4,
    "limitations_stated": 4,
    "key_equations": 3,
    "key_figures": 3,
    "questions": 4,
}
FLAGGED_CAP = 3
EVIDENCE_CAP = 2


def _trim(draft: CardDraft) -> tuple[CardDraft, list[CardWarning]]:
    """The draft with every over-cap list cut to its first N, so dropped items are never
    checked, and an `over_cap` warning per list. The raw response stays in the run trace."""
    warnings: list[CardWarning] = []

    def capped(path: str, items: list, cap: int) -> list:
        if len(items) > cap:
            warnings.append(CardWarning("over_cap", path, f"dropped {len(items) - cap}"))
        return items[:cap]

    def evidence(path: str, f: Fact | Limitation | None):
        if f is None:
            return None
        return f.model_copy(
            update={"evidence": capped(f"{path}.evidence", f.evidence, EVIDENCE_CAP)}
        )

    lists = {name: capped(name, getattr(draft, name), cap) for name, cap in CAPS.items()}
    if not draft.key_results:
        warnings.append(CardWarning("no_key_results", "key_results", "no key results"))
    flagged = draft.opinion.limitations_flagged
    opinion = draft.opinion.model_copy(
        update={"limitations_flagged": capped("opinion.limitations_flagged", flagged, FLAGGED_CAP)}
    )
    for name in ("key_results", "assumptions", "limitations_stated"):
        lists[name] = [evidence(f"{name}[{i}]", f) for i, f in enumerate(lists[name])]
    singles = {
        name: evidence(name, getattr(draft, name))
        for name in ("system", "method", "baselines", "claimed_advance", "code_data")
    }
    return draft.model_copy(update={**lists, **singles, "opinion": opinion}), warnings


def _label_warnings(draft: CardDraft, source: Source) -> list[CardWarning]:
    """Every `key_equations` and `key_figures` label must be in the source; an equation's
    `latex` must sit in its label's (innermost) environment, and a figure's label in a `figure`."""
    warnings = []
    for i, equation in enumerate(draft.key_equations):
        path, label = f"key_equations[{i}]", equation.label
        if label is None:
            continue
        if label not in source.labels:
            warnings.append(CardWarning("unknown_label", path, f"{label} is not in the source"))
            continue
        envs = source.labelled(label)
        latex = canonicalise(equation.latex, source.source_type)
        if not envs or latex not in source.env_body(envs[-1]):
            detail = f"latex is not in the body of {label}"
            warnings.append(CardWarning("equation_mismatch", path, detail))
    for i, figure in enumerate(draft.key_figures):
        path, label = f"key_figures[{i}]", figure.label
        if label not in source.labels:
            warnings.append(CardWarning("unknown_label", path, f"{label} is not in the source"))
        elif not any(env.name == "figure" for env in source.labelled(label)):
            detail = f"{label} is not in a figure environment"
            warnings.append(CardWarning("figure_label_not_figure", path, detail))
    return warnings


def _unique(items) -> list:
    return list(dict.fromkeys(items))


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


def _envs(raw: str, names: list[str]) -> list[tuple[str, int, int, tuple[int, int]]]:
    """(name, start, end, body span) of every environment with one of these names, starred too,
    nesting allowed, in order of their start."""
    spans = []
    open_: list[re.Match] = []
    for m in ENV.finditer(raw):
        kind, name = m.group(1), m.group(2)
        if name not in names:
            continue
        if kind == "begin":
            open_.append(m)
        elif open_ and open_[-1].group(2) == name:
            begin = open_.pop()
            spans.append((name, begin.start(), m.end(), (begin.end(), m.start())))
    return sorted(spans, key=lambda span: span[1])
