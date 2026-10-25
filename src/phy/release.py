"""Releases (SPEC §5): the tagged version `phy daily` runs from, checked out at `$PHY_HOME/app`.

`release_status()` is a stub until the schedule slice: no Release is ever installed.
"""

from dataclasses import dataclass, field

from phy.config import Paths


@dataclass(frozen=True)
class ReleaseStatus:
    installed: str | None
    newest: str | None
    commits: list[str] = field(default_factory=list)  # subjects between installed and newest


def release_status(paths: Paths) -> ReleaseStatus:
    return ReleaseStatus(installed=None, newest=None)
