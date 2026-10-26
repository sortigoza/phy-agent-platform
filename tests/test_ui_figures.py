import io

import pypdfium2 as pdfium
import pytest
from PIL import Image

from phy.config import resolve_paths
from phy.ui.figures import figure_index, image, renderable, resolve

ID, V = "1904.12072", 3


@pytest.fixture
def tree(phy_home):
    paths = resolve_paths()
    root = paths.source_tree(ID, V)
    (root / "figs").mkdir(parents=True)
    return root


def png(width=4, height=3):
    buf = io.BytesIO()
    Image.new("RGB", (width, height), "red").save(buf, "PNG")
    return buf.getvalue()


def pdf(width=200, height=100):
    doc = pdfium.PdfDocument.new()
    doc.new_page(width, height)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_a_png_is_served_as_it_is(tree):
    (tree / "figs" / "flow.png").write_bytes(png())
    assert image(resolve_paths(), ID, V, "figs/flow") == (png(), "image/png")


def test_a_jpg_keeps_its_media_type(tree):
    (tree / "photo.jpg").write_bytes(b"\xff\xd8 jpeg")
    assert image(resolve_paths(), ID, V, "photo.jpg") == (b"\xff\xd8 jpeg", "image/jpeg")


def test_a_pdf_is_rendered_to_png_and_cached_next_to_the_source(tree):
    (tree / "figs" / "autocorr.pdf").write_bytes(pdf())
    data, media_type = image(resolve_paths(), ID, V, "figs/autocorr")
    assert media_type == "image/png"
    rendered = Image.open(io.BytesIO(data))
    assert rendered.format == "PNG"
    assert rendered.width / rendered.height == pytest.approx(2, rel=0.01)
    paths = resolve_paths()
    assert paths.figure_png(ID, V, "figs/autocorr.pdf").read_bytes() == data
    assert image(paths, ID, V, "figs/autocorr.pdf") == (data, "image/png")


def test_an_eps_resolves_but_is_not_renderable(tree):
    (tree / "diagram.eps").write_text("%!PS-Adobe-3.0 EPSF-3.0")
    path = resolve(resolve_paths(), ID, V, "diagram")
    assert path is not None and not renderable(path)
    assert image(resolve_paths(), ID, V, "diagram") is None


def test_a_missing_file_resolves_to_nothing(tree):
    assert resolve(resolve_paths(), ID, V, "figs/nowhere") is None
    assert image(resolve_paths(), ID, V, "figs/nowhere") is None


def test_a_name_cannot_leave_the_source_tree(tree):
    (tree.parent / "flattened.txt").write_text("secret")
    assert resolve(resolve_paths(), ID, V, "../flattened.txt") is None


def test_figure_environments_are_indexed_by_label():
    tex = r"""
\begin{figure*}[t]
\includegraphics[width=0.5\linewidth]{figs/a}\includegraphics{figs/b.pdf}
\caption{Autocorrelation {\it vs} $L$.}
\label{fig:autocorr}
\end{figure*}
\begin{figure}\includegraphics{c}\end{figure}
"""
    index = figure_index(tex)
    assert list(index) == ["fig:autocorr"]
    assert index["fig:autocorr"].files == ["figs/a", "figs/b.pdf"]
    assert index["fig:autocorr"].caption == r"Autocorrelation {\it vs} $L$."
