"""Key figures (SPEC §8, §9): a Card names a figure by its `\\label`; code finds the
`\\includegraphics` files of that `figure` environment in the flattened text and resolves them
in the Paper version's source tree. PNG and JPG are served as they are, a PDF is rendered to PNG
with pypdfium2 (cached next to the source), and EPS is not renderable.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium

from phy.config import Paths
from phy.ui.latex import braced

FIGURE = re.compile(r"\\begin\{figure\*?\}(.+?)\\end\{figure\*?\}", re.S)
LABEL = re.compile(r"\\label\{([^{}]+)\}")
INCLUDEGRAPHICS = re.compile(r"\\includegraphics\*?\s*(?:\[[^\]]*\])?\s*\{([^{}]+)\}")
CAPTION = re.compile(r"\\caption\s*(?:\[[^\]]*\])?\s*(?=\{)")
# pdflatex's own search order for a name without an extension, then EPS for the old toolchain.
EXTENSIONS = ["", ".pdf", ".png", ".jpg", ".jpeg", ".eps"]
MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
RENDERABLE = {*MEDIA_TYPES, ".pdf"}
RENDER_WIDTH_PX = 1100


@dataclass(frozen=True)
class FigureEnv:
    files: list[str]  # as written in \includegraphics
    caption: str  # raw LaTeX


def figure_index(tex: str) -> dict[str, FigureEnv]:
    """Every labelled `figure` environment in the text, by label."""
    index = {}
    for env in FIGURE.finditer(tex):
        body = env.group(1)
        label = LABEL.search(body)
        if not label:
            continue
        caption = CAPTION.search(body)
        index[label.group(1)] = FigureEnv(
            files=INCLUDEGRAPHICS.findall(body),
            caption=(braced(body, caption.end()) or "") if caption else "",
        )
    return index


def resolve(paths: Paths, arxiv_id: str, version: int, name: str) -> Path | None:
    """The file an `\\includegraphics{name}` points at in the source tree, or None."""
    root = paths.source_tree(arxiv_id, version).resolve()
    for ext in EXTENSIONS:
        path = (root / f"{name}{ext}").resolve()
        if path.is_relative_to(root) and path.is_file():
            return path
    return None


def renderable(path: Path) -> bool:
    return path.suffix.lower() in RENDERABLE


def image(paths: Paths, arxiv_id: str, version: int, name: str) -> tuple[bytes, str] | None:
    """The figure's bytes and media type, or None when it is missing or not renderable."""
    path = resolve(paths, arxiv_id, version, name)
    if path is None or not renderable(path):
        return None
    suffix = path.suffix.lower()
    if suffix in MEDIA_TYPES:
        return path.read_bytes(), MEDIA_TYPES[suffix]
    root = paths.source_tree(arxiv_id, version).resolve()
    cache = paths.figure_png(arxiv_id, version, str(path.relative_to(root)))
    if not cache.is_file():
        page = pdfium.PdfDocument(path)[0]
        cache.parent.mkdir(parents=True, exist_ok=True)
        page.render(scale=RENDER_WIDTH_PX / page.get_width()).to_pil().save(cache, "PNG")
    return cache.read_bytes(), "image/png"
