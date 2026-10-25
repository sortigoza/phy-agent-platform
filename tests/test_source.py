import gzip
import tarfile

import pytest
from archives import tar_gz

from phy.read.source import UnknownSourceFormat, detect, unpack

TEX = rb"\documentclass{article}\begin{document}Hi\end{document}"


def test_gzip_then_tar_is_a_tarball():
    assert detect(tar_gz({"main.tex": TEX})) == "tar.gz"


def test_gzip_without_tar_is_a_single_tex_file():
    assert detect(gzip.compress(TEX)) == "tex.gz"


def test_pdf_magic_is_a_pdf():
    assert detect(b"%PDF-1.7\n...") == "pdf"


def test_anything_else_is_refused():
    with pytest.raises(UnknownSourceFormat):
        detect(b"<html>not found</html>")


def test_tarball_unpacks_its_tree(tmp_path):
    unpack(tar_gz({"main.tex": TEX, "sec/intro.tex": b"Intro"}), "tar.gz", tmp_path)

    assert (tmp_path / "main.tex").read_bytes() == TEX
    assert (tmp_path / "sec" / "intro.tex").read_bytes() == b"Intro"


def test_tarball_members_outside_the_tree_are_refused(tmp_path):
    with pytest.raises(tarfile.TarError):
        unpack(tar_gz({"../escape.tex": TEX}), "tar.gz", tmp_path / "src")
    assert not (tmp_path / "escape.tex").exists()


def test_single_gzipped_tex_unpacks_to_main_tex(tmp_path):
    unpack(gzip.compress(TEX), "tex.gz", tmp_path)

    assert (tmp_path / "main.tex").read_bytes() == TEX
