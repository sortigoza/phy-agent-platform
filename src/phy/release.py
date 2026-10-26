"""Releases (SPEC §5): the tagged version `phy daily` runs from, checked out at `$PHY_HOME/app`.

A Release is an annotated tag `vMAJOR.MINOR.PATCH` that the Reader cuts; phy never tags.
Everything here is local git: the worktree at `$PHY_HOME/app` shares the dev repo's tags, so
no fetch is needed to see a newer Release.
"""

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import structlog

from phy import config
from phy.config import Paths

log = structlog.get_logger()

RELEASE = re.compile(r"v\d+\.\d+\.\d+")


class ReleaseError(Exception):
    """A git command failed, or the Release asked for cannot be installed."""


class Downgrade(ReleaseError):
    """The newest Release does not contain the installed one (its tag was deleted or moved)."""


@dataclass(frozen=True)
class ReleaseStatus:
    installed: str | None
    newest: str | None
    commits: list[str] = field(default_factory=list)  # subjects between installed and newest

    @property
    def update_available(self) -> bool:
        return bool(self.commits)


def git(repo: Path, *args: str) -> str:
    try:
        done = subprocess.run(
            ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
        )
    except FileNotFoundError:
        raise ReleaseError("git not found") from None
    except subprocess.CalledProcessError as e:
        raise ReleaseError(f"git {' '.join(args)}: {e.stderr.strip()}") from None
    return done.stdout.strip()


def newest(repo: Path) -> str | None:
    """The highest annotated `vX.Y.Z` tag on `main`; lightweight and pre-release tags, and tags
    on other branches, are not Releases."""
    return next(iter(_releases(repo, "--merged", "main")), None)


def installed(paths: Paths) -> str | None:
    """The Release checked out at `$PHY_HOME/app`, or what `git describe` makes of HEAD when no
    Release tag points at it (a tag deleted or moved since)."""
    if not paths.app.exists():
        return None
    tags = _releases(paths.app, "--points-at", "HEAD")
    return tags[0] if tags else git(paths.app, "describe", "--tags")


def _releases(repo: Path, *selection: str) -> list[str]:
    """Release tags among those `selection` picks, highest first."""
    listed = git(
        repo,
        "tag",
        "--list",
        "v*",
        *selection,
        "--sort=-v:refname",
        "--format=%(objecttype) %(refname:strip=2)",
    )
    return [
        name
        for kind, name in (line.split(" ", 1) for line in listed.splitlines())
        if kind == "tag" and RELEASE.fullmatch(name)
    ]


def pending(paths: Paths, tag: str) -> list[str]:
    """Subjects of the commits `tag` adds to the installed Release, newest first. Empty when
    `tag` is what is installed; raises Downgrade when installing it would go backwards."""
    if git(paths.app, "rev-parse", "HEAD") == git(paths.app, "rev-parse", f"{tag}^{{commit}}"):
        return []
    try:
        git(paths.app, "merge-base", "--is-ancestor", "HEAD", tag)
    except ReleaseError:
        raise Downgrade(
            f"{tag} does not contain the installed {installed(paths)}; refusing to downgrade"
        ) from None
    return git(paths.app, "log", "--format=%s", f"HEAD..{tag}").splitlines()


def release_status(paths: Paths, repo: Path | None = None) -> ReleaseStatus:
    """Never raises: a broken checkout shows as nothing installed, logged, rather than breaking
    a page."""
    try:
        now = installed(paths)
        latest = newest(repo or config.REPO)
        commits = pending(paths, latest) if now and latest else []
    except Downgrade as e:
        log.warning("release.downgrade_found", error=str(e))
        commits = []
    except ReleaseError as e:
        log.warning("release.status_failed", error=str(e))
        return ReleaseStatus(installed=None, newest=None)
    return ReleaseStatus(installed=now, newest=latest, commits=commits)
