"""Process locks under `$PHY_HOME`, both `fcntl.flock`, so they are released when the holder
dies and never go stale.

- `phy_lock`: non-blocking. Taken by `daily` and every Stage command; if another process holds
  it, the command logs and exits 0.
- `arxiv_lock`: blocking. Serialises arXiv requests across processes and keeps the time of the
  last request in the lock file, so the rate limiter can wait out the interval while holding it.
"""

import fcntl
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import IO

import structlog

from phy.config import Paths

log = structlog.get_logger()


@contextmanager
def phy_lock(paths: Paths) -> Iterator[None]:
    with open(paths.phy_lock, "a") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log.info("lock.held", lock=paths.phy_lock.name)
            sys.exit(0)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


@dataclass
class ArxivSlot:
    """The arXiv lock while held: when the last request was made, and a way to record the next."""

    last_request_at: float | None
    _file: IO[str]

    def mark(self, timestamp: float) -> None:
        self._file.seek(0)
        self._file.truncate()
        self._file.write(repr(timestamp))
        self._file.flush()
        os.fsync(self._file.fileno())
        self.last_request_at = timestamp


@contextmanager
def arxiv_lock(paths: Paths) -> Iterator[ArxivSlot]:
    fd = os.open(paths.arxiv_lock, os.O_RDWR | os.O_CREAT, 0o644)
    with os.fdopen(fd, "r+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            text = f.read().strip()
            yield ArxivSlot(last_request_at=float(text) if text else None, _file=f)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
