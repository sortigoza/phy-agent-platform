"""Source to `flattened.txt` (SPEC §7.3): `flatten()` for a LaTeX tree, `pdf_text()` for a PDF.

The LaTeX flattener is stdlib only, with no TeX parsing. Its output is raw LaTeX, never detexed:
it is the text the model reads and quotes from and the text Verify checks quotes against.
Macros, `\\label`, `\\ref`, `\\cite` and math stay verbatim.
"""

import json
import re
import unicodedata
from pathlib import Path

import pypdfium2 as pdfium
import structlog

log = structlog.get_logger()

MAX_INPUT_DEPTH = 20

COMMENT = re.compile(r"(?<!\\)((?:\\\\)*)%.*")
COMMENT_ENV = re.compile(r"\\begin\{comment\}.*?\\end\{comment\}", re.S)
DOCUMENTCLASS = re.compile(r"\\document(?:class|style)(?![a-zA-Z@])")
INPUT = re.compile(r"\\(?:input|include)(?![a-zA-Z@])\s*(?:\{([^}]*)\}|([^\s{}%\\]+))")
IFFALSE = re.compile(r"\\iffalse(?![a-zA-Z@])")
CONDITIONAL = re.compile(r"\\(if[a-zA-Z@]*|else|fi)(?![a-zA-Z@])")
NOT_CONDITIONALS = {"iff", "ifthenelse"}  # macros that look like \if... but have no \fi
END_DOCUMENT = re.compile(r"(\\end\{document\}).*", re.S)
THEBIBLIOGRAPHY = re.compile(r"\\begin\{thebibliography\}.*?\\end\{thebibliography\}", re.S)
BIB_COMMANDS = re.compile(
    r"\\(?:bibliography|bibliographystyle|addbibresource)\{[^}]*\}"
    r"|\\printbibliography(?:\[[^\]]*\])?"
)


# pdfium marks a hyphen it joined at a line break as U+0002, and soft hyphens as U+FFFE.
SOFT_HYPHEN = re.compile("[\u0002\ufffe\u00ad]\n?")
HYPHENATED_BREAK = re.compile(r"(\w)-\n(\w)")


class NoMainFile(Exception):
    pass


def flatten(root: Path) -> str:
    main = find_main(root)
    tex = _inline(root, main, stack=[])
    tex = END_DOCUMENT.sub(r"\1\n", tex, count=1)
    tex = THEBIBLIOGRAPHY.sub("", tex)
    tex = BIB_COMMANDS.sub("", tex)
    return re.sub(r"\n{3,}", "\n\n", tex)


def find_main(root: Path) -> Path:
    """The `00README` toplevel file, else the largest `.tex` with an uncommented
    `\\documentclass` (arXiv's own rule; extra candidates are logged)."""
    toplevel = _readme_toplevel(root)
    if toplevel is not None:
        if (root / toplevel).is_file():
            return root / toplevel
        log.warning("read.toplevel_missing", file=toplevel)
    candidates = [
        path
        for path in sorted(root.rglob("*.tex"))
        if path.is_file() and DOCUMENTCLASS.search(_strip_comments(_read(path)))
    ]
    if not candidates:
        raise NoMainFile(f"no 00README toplevel and no .tex file with \\documentclass in {root}")
    main = max(candidates, key=lambda path: path.stat().st_size)
    if len(candidates) > 1:
        others = [str(path.relative_to(root)) for path in candidates if path != main]
        log.warning("read.main_ambiguous", main=str(main.relative_to(root)), others=others)
    return main


def _readme_toplevel(root: Path) -> str | None:
    readme_json = root / "00README.json"
    if readme_json.is_file():
        try:
            sources = json.loads(readme_json.read_text()).get("sources", [])
        except (json.JSONDecodeError, AttributeError):
            log.warning("read.readme_unparsed", file=readme_json.name)
            sources = []
        for source in sources:
            if isinstance(source, dict) and source.get("usage") == "toplevel":
                return source.get("filename")
    for readme in [root / "00README.XXX", root / "00README"]:
        if readme.is_file():
            for line in _read(readme).splitlines():
                words = line.split()
                if len(words) >= 2 and words[1] == "toplevel":
                    return words[0]
    return None


def _inline(root: Path, path: Path, stack: list[Path]) -> str:
    tex = _strip_comments(_read(path))
    tex = COMMENT_ENV.sub("", tex)
    tex = _drop_iffalse(tex)
    stack = [*stack, path.resolve()]

    def replace(match: re.Match) -> str:
        name = (match.group(1) or match.group(2)).strip()
        target = _resolve_input(root, path.parent, name)
        if target is None:
            log.warning("read.input_missing", file=name)
            return match.group(0)
        if target.resolve() in stack or len(stack) >= MAX_INPUT_DEPTH:
            log.warning("read.input_cycle", file=name)
            return match.group(0)
        return _inline(root, target, stack).removesuffix("\n")  # the \input line has its own

    return INPUT.sub(replace, tex)


def _resolve_input(root: Path, current: Path, name: str) -> Path | None:
    """Root-relative first (arXiv compiles from the root), then relative to the including file;
    `.tex` added if missing. Never outside the tree."""
    for base in [root, current]:
        for candidate in [base / name, base / f"{name}.tex"]:
            if candidate.is_file() and candidate.resolve().is_relative_to(root.resolve()):
                return candidate
    return None


def _read(path: Path) -> str:
    data = path.read_bytes()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _strip_comments(tex: str) -> str:
    """Drop `%` to end of line (not `\\%`); a line that was only a comment goes entirely."""
    lines = []
    for line in tex.splitlines():
        stripped = COMMENT.sub(r"\1", line)
        if stripped == line:
            lines.append(line)
        elif stripped.strip():
            lines.append(stripped.rstrip())
    return "\n".join(lines) + "\n"


def _drop_iffalse(tex: str) -> str:
    """Remove `\\iffalse … \\fi`, keeping an `\\else` branch; nested conditionals are counted."""
    out = []
    pos = 0
    while match := IFFALSE.search(tex, pos):
        depth = 1
        keep_from = None
        for token in CONDITIONAL.finditer(tex, match.end()):
            word = token.group(1)
            if word == "fi":
                depth -= 1
            elif word == "else":
                if depth == 1 and keep_from is None:
                    keep_from = token.end()
            elif word not in NOT_CONDITIONALS:
                depth += 1
            if depth == 0:
                out.append(tex[pos : match.start()])
                if keep_from is not None:
                    out.append(tex[keep_from : token.start()])
                pos = token.end()
                break
        else:
            log.warning("read.iffalse_unterminated")
            break
    out.append(tex[pos:])
    return "".join(out)


def pdf_text(path: Path) -> str:
    """Page texts joined by `\\f`, with soft hyphens stripped, hyphenated line breaks joined
    and NFKC applied, so page numbers can serve as locations."""
    pdf = pdfium.PdfDocument(path)
    try:
        pages = []
        for page in pdf:
            textpage = page.get_textpage()
            pages.append(_normalize_pdf_text(textpage.get_text_bounded()))
            textpage.close()
            page.close()
    finally:
        pdf.close()
    return "\f".join(pages)


def _normalize_pdf_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = SOFT_HYPHEN.sub("", text)
    text = HYPHENATED_BREAK.sub(r"\1\2", text)
    return unicodedata.normalize("NFKC", text)
