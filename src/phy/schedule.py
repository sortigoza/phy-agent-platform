"""`phy schedule` (SPEC §5): a launchd agent that runs `phy daily` from the installed Release.

The Release is a detached git worktree of the dev repo at `$PHY_HOME/app`, so work in progress
in the clone never runs unattended. `launchctl` and `uv sync` each go through one function that
tests replace. The CLI holds `phy.lock` around install, update and uninstall, so none of them
pulls the code from under a running `phy daily`.
"""

import os
import plistlib
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import structlog

from phy import config, db, release
from phy.config import Paths
from phy.release import ReleaseError, git

log = structlog.get_logger()

LABEL = "phy.daily"
LAST_RUN = "daily.last_run_at"  # when `phy daily` last finished, scheduled or not
BOOTSTRAP_ATTEMPTS = 10  # `launchctl bootout` returns before the job is gone


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
    """Outside `$PHY_HOME`: launchd only reads agents from here."""
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _service() -> str:
    return f"{_domain()}/{LABEL}"


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
    is: `update` moves it), sync its environment, and load the job. Returns the installed
    Release. Running it again changes nothing: a loaded job with the same plist is not
    reloaded, which would start another run (`RunAtLoad`)."""
    repo = repo or config.REPO
    if not paths.app.exists():
        tag = release.newest(repo)
        if tag is None:
            raise ReleaseError(
                "no Release to install: tag one on main first, e.g. git tag -a v0.1.0 -m ..."
            )
        git(repo, "worktree", "prune")  # forget a checkout deleted by hand
        git(repo, "worktree", "add", "--detach", str(paths.app), tag)
    _ignore_app(paths)
    uv_sync(paths.app)

    paths.logs.mkdir(parents=True, exist_ok=True)
    agent = agent_plist()
    wanted = plist(paths, find_uv())
    loaded = launchctl("print", _service()).returncode == 0
    if not (loaded and agent.exists() and agent.read_bytes() == wanted):
        agent.parent.mkdir(parents=True, exist_ok=True)
        agent.write_bytes(wanted)
        if loaded:
            launchctl("bootout", _service())
        _bootstrap(agent)
    installed = release.installed(paths)
    log.info("schedule.installed", release=installed)
    return installed


def _bootstrap(agent: Path) -> None:
    for attempt in range(BOOTSTRAP_ATTEMPTS):
        done = launchctl("bootstrap", _domain(), str(agent))
        if done.returncode == 0:
            return
        time.sleep(0.5 * (attempt + 1))
    raise ReleaseError(f"launchctl bootstrap {agent}: {done.stderr.strip()}")


def _ignore_app(paths: Paths) -> None:
    """`phy init` seeds the ignore line; an older `$PHY_HOME` gets it here."""
    lines = paths.gitignore.read_text().splitlines() if paths.gitignore.exists() else []
    if "app/" not in lines:
        with paths.gitignore.open("a") as f:
            f.write("app/\n")


def update(paths: Paths, repo: Path | None = None) -> Updated | None:
    """Move `$PHY_HOME/app` to the newest Release and sync it; None when already there.
    Migrations apply on the next connect."""
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
    """Reads the db without migrating it: this may run from code newer than the Release."""
    printed = launchctl("print", _service())
    loaded = printed.returncode == 0
    exit_code = re.search(r"last exit code = (\d+)", printed.stdout) if loaded else None
    return ScheduleStatus(
        loaded=loaded,
        installed=release.installed(paths),
        last_run_at=db.read_state(paths.db, LAST_RUN),
        last_exit=exit_code.group(1) if exit_code else None,
    )


def uninstall(paths: Paths, repo: Path | None = None) -> None:
    """Unload the job and remove the plist and the worktree. The data in `$PHY_HOME` stays."""
    repo = repo or config.REPO
    launchctl("bootout", _service())
    agent_plist().unlink(missing_ok=True)
    if paths.app.exists():
        git(repo, "worktree", "remove", "--force", str(paths.app))
    git(repo, "worktree", "prune")
    log.info("schedule.uninstalled")


def render(s: ScheduleStatus) -> str:
    job = (
        f"job: loaded ({LABEL}, 06:00 daily and at login)"
        if s.loaded
        else "job: not loaded; run `phy schedule install`"
    )
    if s.last_run_at:
        last = f"{datetime.fromisoformat(s.last_run_at).astimezone(UTC):%Y-%m-%d %H:%M} UTC"
    else:
        last = "never"
    if s.last_exit is not None:
        last += f", launchd exit code {s.last_exit}"
    return "\n".join([job, f"release: {s.installed or 'none installed'}", f"last run: {last}"])


def render_update(updated: Updated | None, paths: Paths) -> str:
    if updated is None:
        return f"already on the newest Release, {release.installed(paths)}"
    n = len(updated.commits)
    head = f"updated {updated.previous} -> {updated.installed} ({n} commit{'s' * (n != 1)}):"
    return "\n".join([head, *(f"  {subject}" for subject in updated.commits)])
