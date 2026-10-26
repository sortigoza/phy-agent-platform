"""LaTeX for display only (SPEC §9): KaTeX macros from the preamble, and a cleanup of text
markup. Math is left for KaTeX auto-render in the browser; unknown commands stay raw.
"""

import html
import re

from phy.ui.help import HELP

DEFINITION = re.compile(
    r"\\(?:(?:(?:re)?newcommand|providecommand)\*?\s*(?:\{(\\[A-Za-z]+)\}|(\\[A-Za-z]+))"
    r"\s*(?:\[\d\])?(?P<default>\s*\[)?|def\s*(\\[A-Za-z]+))\s*(?=\{)"
)
MATH = re.compile(r"(\$\$.+?\$\$|\$.+?\$|\\\(.+?\\\)|\\\[.+?\\\])", re.S)


def preamble_macros(tex: str) -> dict[str, str]:
    """`\\newcommand{\\name}[n]{body}` (and `\\renewcommand`, `\\providecommand`, `\\def`) in
    the preamble as KaTeX macros `{"\\name": "body"}`; KaTeX reads `#1`… itself. A macro with
    an optional argument is left out, since KaTeX macros can't have one."""
    end = tex.find("\\begin{document}")
    preamble = tex if end == -1 else tex[:end]
    macros = {}
    for m in DEFINITION.finditer(preamble):
        if m.group("default"):
            continue
        body = braced(preamble, m.end())
        if body is not None:
            macros[m.group(1) or m.group(2) or m.group(4)] = body
    return macros


def braced(tex: str, at: int) -> str | None:
    """The content of the balanced `{…}` opening at `at`, skipping escaped braces."""
    depth, i = 0, at
    while i < len(tex):
        char = tex[i]
        if char == "\\":
            i += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return tex[at + 1 : i]
        i += 1
    return None


def tex_html(s: str) -> str:
    """HTML for a Card value or quote: math escaped and left for KaTeX, text markup cleaned."""
    parts = MATH.split(s)
    return "".join(
        html.escape(p, quote=False) if i % 2 else _clean_text(p) for i, p in enumerate(parts)
    )


def _clean_text(s: str) -> str:
    s = html.escape(s, quote=False)
    s = re.sub(r"\{\\(?:it|em)\s+([^{}]*)\}", r"<i>\1</i>", s)
    s = re.sub(r"\{\\bf\s+([^{}]*)\}", r"<b>\1</b>", s)
    s = re.sub(r"\\(?:textit|emph)\{([^{}]*)\}", r"<i>\1</i>", s)
    s = re.sub(r"\\textbf\{([^{}]*)\}", r"<b>\1</b>", s)
    ref = f'<span class="ref" title="{html.escape(HELP["ref"])}">'
    s = re.sub(r"\\(?:eq)?ref\{([^{}]*)\}", ref + r"\1</span>", s)
    s = re.sub(r"\\cite[pt]?\{[^{}]*\}", ref + "cite</span>", s)
    s = s.replace("~", " ").replace("\\%", "%").replace("---", "—").replace("--", "–")
    return s.replace("``", "“").replace("''", "”")
