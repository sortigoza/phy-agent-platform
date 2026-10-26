"""`phy schedule` (SPEC §5): a launchd agent that runs `phy daily` from the installed Release.

The Release is a detached git worktree of the dev repo at `$PHY_HOME/app`, so work in progress
in the clone never runs unattended. `launchctl` and `uv sync` each go through one function that
tests replace.
"""

import os
import plistlib
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import structlog

from phy import config, db, release
from phy.config import Paths
from phy.daily import LAST_RUN
from phy.release import ReleaseError, git

log = structlog.get_logger()

LABEL = "phy.daily"


def launchctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def uv_sync(app: Path) -> None:
    try:
        subprocess.run([find_uv(), "sync", "--frozen"], cwd=app, check=True)
    except subprocess.CalledProcessError as e:
        raise ReleaseError(f"uv sync in {app} failed with exit code {e.returncode}") from None


def find_uv() -> str:
    """`uv run` sets `UV` to its own path; otherwise look on PATH."""
    uv = os.environ.get("UV") or shutil.which("uv")
    if not uv:
        raise ReleaseError("uv not found on PATH")
    return str(Path(uv).absolute())  # not resolved: a Homebrew Cellar path dies on upgrade


def agent_plist() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _domain() -> str:
    return f"gui/{os.getuid()}"


def plist(paths: Paths, uv: str) -> bytes:
    """`uv` is absolute: launchd's PATH is bare and it never reads shell profiles. Only
    `PHY_HOME` goes in the environment; credentials come from the `ant auth login` profile."""
    return plistlib.dumps(
        {
            "Label": LABEL,
            "ProgramArguments": [uv, "run", "--frozen", "phy", "daily"],
            "WorkingDirectory": str(paths.app),
            "EnvironmentVariables": {"PHY_HOME": str(paths.home)},
            "StartCalendarInterval": {"Hour": 6, "Minute": 0},
            "RunAtLoad": True,
            "StandardErrorPath": str(paths.launchd_err),
        }
    )


@dataclass(frozen=True)
class ScheduleStatus:
    loaded: bool
    installed: str | None
    last_run_at: str | None  # when `phy daily` last finished, scheduled or not
    last_exit: str | None  # launchd's last exit code of the job; None if it never exited


@dataclass(frozen=True)
class Updated:
    previous: str
    installed: str
    commits: list[str]  # subjects, newest first


def install(paths: Paths, repo: Path | None = None) -> str:
    """Check out the newest Release at `$PHY_HOME/app` (an existing checkout is left where it
    is: `update` moves it), sync its environment, and (re)load the job. Returns the installed
    Release. Running it again changes nothing."""
    repo = repo or config.REPO
    if not paths.app.exists():
        tag = release.newest(repo)
        if tag is None:
            raise ReleaseError(
                "no Release to install: tag one on main first, e.g. git tag -a v0.1.0 -m ..."
            )
        git(repo, "worktree", "add", "--detach", str(paths.app), tag)
    _ignore_app(paths)
    uv_sync(paths.app)

    paths.logs.mkdir(parents=True, exist_ok=True)
    agent = agent_plist()
    agent.parent.mkdir(parents=True, exist_ok=True)
    agent.write_bytes(plist(paths, find_uv()))
    launchctl("bootout", f"{_domain()}/{LABEL}")  # fails when not loaded, which is fine
    loaded = launchctl("bootstrap", _domain(), str(agent))
    if loaded.returncode != 0:
        raise ReleaseError(f"launchctl bootstrap {agent}: {loaded.stderr.strip()}")
    installed = release.installed(paths)
    log.info("schedule.installed", release=installed)
    return installed


def _ignore_app(paths: Paths) -> None:
    """`phy init` seeds the ignore line; an older `$PHY_HOME` gets it here."""
    lines = paths.gitignore.read_text().splitlines() if paths.gitignore.exists() else []
    if "app/" not in lines:
        with paths.gitignore.open("a") as f:
            f.write("app/\n")


def update(paths: Paths, repo: Path | None = None) -> Updated | None:
    """Move `$PHY_HOME/app` to the newest Release and sync it; None when already there. The
    caller holds `phy.lock`, so no run is mid-flight; migrations apply on the next connect."""
    previous = release.installed(paths)
    if previous is None:
        raise ReleaseError("no Release installed; run `phy schedule install` first")
    tag = release.newest(repo or config.REPO)
    if tag is None:
        raise ReleaseError("no Release tagged")
    commits = release.pending(paths, tag)
    if not commits:
        return None
    git(paths.app, "checkout", "-q", "--detach", tag)
    uv_sync(paths.app)
    log.info("schedule.updated", previous=previous, release=tag, commits=len(commits))
    return Updated(previous=previous, installed=tag, commits=commits)


def status(paths: Paths) -> ScheduleStatus:
    printed = launchctl("print", f"{_domain()}/{LABEL}")
    loaded = printed.returncode == 0
    exit_code = re.search(r"last exit code = (\S+)", printed.stdout) if loaded else None
    last_run_at = None
    if paths.db.exists():
        conn = db.connect(paths.db)
        try:
            last_run_at = db.get_state(conn, LAST_RUN)
        finally:
            conn.close()
    return ScheduleStatus(
        loaded=loaded,
        installed=release.installed(paths),
        last_run_at=last_run_at,
        last_exit=exit_code.group(1) if exit_code and exit_code.group(1).isdigit() else None,
    )


def uninstall(paths: Paths, repo: Path | None = None) -> None:
    """Unload the job and remove the plist and the worktree. The data in `$PHY_HOME` stays."""
    launchctl("bootout", f"{_domain()}/{LABEL}")
    agent_plist().unlink(missing_ok=True)
    if paths.app.exists():
        git(repo or config.REPO, "worktree", "remove", "--force", str(paths.app))
    log.info("schedule.uninstalled")


def render(s: ScheduleStatus) -> str:
    job = (
        f"job: loaded ({LABEL}, 06:00 daily and at login)"
        if s.loaded
        else "job: not loaded; run `phy schedule install`"
    )
    if s.last_run_at:
        last = (
            f"last run: {datetime.fromisoformat(s.last_run_at).astimezone(UTC):%Y-%m-%d %H:%M} UTC"
        )
    else:
        last = "last run: never"
    if s.last_exit is not None:
        last += f", launchd exit code {s.last_exit}"
    return "\n".join([job, f"release: {s.installed or 'none installed'}", last])
