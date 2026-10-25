import io
import tarfile


def tar_gz(files: dict[str, bytes]) -> bytes:
    """A gzipped tarball of `files`, as arxiv.org/src/ serves a LaTeX submission."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return buffer.getvalue()
