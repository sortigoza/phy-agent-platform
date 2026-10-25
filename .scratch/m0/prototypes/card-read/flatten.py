"""PROTOTYPE, throwaway. Just enough flattening to feed one real Read call on a
single-file paper (1904.12072). The real flattener is decided in the LaTeX
tooling ticket; this skips \\input inlining and 00README handling."""

import re
import sys
from pathlib import Path


def strip_comments(tex: str) -> str:
    out = []
    for line in tex.splitlines():
        m = re.search(r"(?<!\\)%", line)
        if m:
            line = line[: m.start()]
            if not line.strip():
                continue  # full-line comment: drop the line entirely
        out.append(line)
    return "\n".join(out)


def flatten(tex: str) -> str:
    tex = strip_comments(tex)
    tex = re.sub(r"\\begin\{comment\}.*?\\end\{comment\}", "", tex, flags=re.S)
    tex = re.sub(r"\\iffalse\b.*?\\fi\b", "", tex, flags=re.S)
    tex = re.sub(r"\\end\{document\}.*", r"\\end{document}\n", tex, flags=re.S)
    tex = re.sub(r"\\begin\{thebibliography\}.*?\\end\{thebibliography\}", "", tex, flags=re.S)
    tex = re.sub(r"^\\bibliography(style)?\{[^}]*\}\s*$", "", tex, flags=re.M)
    return re.sub(r"\n{3,}", "\n\n", tex)


if __name__ == "__main__":
    src = Path(sys.argv[1])
    Path(sys.argv[2]).write_text(flatten(src.read_text()))
