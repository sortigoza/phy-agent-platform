"""What `arxiv.org/src/<id>v<n>` returned, told apart by magic bytes (SPEC §7.3).

gzip then tar is a source tarball, gzip alone is a single gzipped `.tex`, `%PDF` is a PDF.
"""

import gzip
import io
import tarfile
from pathlib import Path
from typing import Literal

SourceFormat = Literal["tar.gz", "tex.gz", "pdf"]

GZIP_MAGIC = b"\x1f\x8b"
PDF_MAGIC = b"%PDF"
TAR_MAGIC_OFFSET = 257  # "ustar" in the first tar header


class UnknownSourceFormat(Exception):
    pass


def detect(data: bytes) -> SourceFormat:
    if data.startswith(PDF_MAGIC):
        return "pdf"
    if data.startswith(GZIP_MAGIC):
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as f:
            head = f.read(TAR_MAGIC_OFFSET + 5)
        return "tar.gz" if head[TAR_MAGIC_OFFSET:] == b"ustar" else "tex.gz"
    raise UnknownSourceFormat(f"not gzip or PDF (starts {data[:8]!r})")


def unpack(data: bytes, fmt: SourceFormat, dest: Path) -> None:
    """Write the LaTeX tree into `dest`: the tarball's files, or the single `.tex` as `main.tex`."""
    dest.mkdir(parents=True, exist_ok=True)
    if fmt == "tar.gz":
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            tar.extractall(dest, filter="data")
    elif fmt == "tex.gz":
        (dest / "main.tex").write_bytes(gzip.decompress(data))
    else:
        raise ValueError(f"{fmt} has no LaTeX tree")
