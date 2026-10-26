"""Releases and the launchd schedule, against a temporary git repo; launchctl and uv replaced."""

import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from phy import config, db, release, schedule
from phy.cli import app
from phy.config import Paths, resolve_paths
from phy.locks import phy_lock

FIXTURES = Path(__file__).parent / "fixtures" / "schedule"


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A dev repo whose commits are named by `commit(subject)` and tagged by `tag(name)`."""
    for var in ["AUTHOR", "COMMITTER"]:
        monkeypatch.setenv(f"GIT_{var}_NAME", "Reader")
        monkeypatch.setenv(f"GIT_{var}_EMAIL", "reader@example.com")
    path = tmp_path / "dev"
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    return path


class Launchd:
    """Stands in for `launchctl` and `uv sync`: records calls, keeps whether the job is loaded."""

    def __init__(self):
        self.calls = []
        self.synced = []
        self.loaded = False
        self.last_exit = "(never exited)"

    def launchctl(self, *args):
        self.calls.append(args)
        returncode, stdout = 0, ""
        match args[0]:
            case "bootstrap":
                self.loaded = True
            case "bootout":
                returncode, self.loaded = (0 if self.loaded else 3), False
            case "print":
                returncode = 0 if self.loaded else 113
                stdout = f"\tstate = not running\n\tlast exit code = {self.last_exit}\n"
        return subprocess.CompletedProcess(args, returncode, stdout, "")


@pytest.fixture
def launchd(phy_home, monkeypatch):
    fake = Launchd()
    monkeypatch.setattr(schedule, "launchctl", fake.launchctl)
    monkeypatch.setattr(schedule, "uv_sync", fake.synced.append)
    monkeypatch.setenv("UV", "/opt/homebrew/bin/uv")
    phy_home.mkdir()
    (phy_home / ".gitignore").write_text("phy.db\n")
    return fake


def commit(repo, subject):
    git(repo, "commit", "-q", "--allow-empty", "-m", subject)


def tag(repo, name, annotated=True):
    git(repo, "tag", *(["-a", "-m", name] if annotated else []), name)


def test_the_newest_release_is_the_highest_annotated_semver_tag(repo):
    assert release.newest(repo) is None
    commit(repo, "First")
    tag(repo, "v0.1.0")
    commit(repo, "Second")
    tag(repo, "v0.2.0")
    tag(repo, "v0.10.0-light", annotated=False)
    commit(repo, "Third")
    tag(repo, "v0.3.0-rc1")
    tag(repo, "v9.9.9", annotated=False)
    assert release.newest(repo) == "v0.2.0"


def test_the_plist_runs_phy_daily_from_the_release_with_the_absolute_uv_path():
    paths = Paths(home=Path("/Users/reader/.phy-agent-platform"))
    plist = schedule.plist(paths, uv="/opt/homebrew/bin/uv")
    assert plist == (FIXTURES / "phy.daily.plist").read_bytes()


def test_install_refuses_when_there_is_no_release(repo, launchd):
    commit(repo, "First")
    with pytest.raises(release.ReleaseError, match="no Release"):
        schedule.install(resolve_paths(), repo)
    assert launchd.calls == [] and not resolve_paths().app.exists()


def test_install_checks_out_the_newest_release_and_loads_the_job(repo, launchd):
    commit(repo, "First")
    tag(repo, "v0.1.0")
    commit(repo, "Work in progress")
    paths = resolve_paths()

    assert schedule.install(paths, repo) == "v0.1.0"

    assert release.installed(paths) == "v0.1.0"
    assert git(paths.app, "log", "-1", "--format=%s") == "First"
    assert launchd.synced == [paths.app]
    agent = Path.home() / "Library" / "LaunchAgents" / "phy.daily.plist"
    assert agent.read_bytes() == schedule.plist(paths, "/opt/homebrew/bin/uv")
    assert ("bootstrap", f"gui/{os.getuid()}", str(agent)) in launchd.calls
    assert launchd.loaded
    assert "app/" in paths.gitignore.read_text().splitlines()
    assert paths.logs.is_dir()


def test_install_twice_changes_nothing(repo, launchd):
    commit(repo, "First")
    tag(repo, "v0.1.0")
    paths = resolve_paths()
    schedule.install(paths, repo)
    gitignore = paths.gitignore.read_text()

    assert schedule.install(paths, repo) == "v0.1.0"
    assert launchd.loaded
    assert paths.gitignore.read_text() == gitignore


@pytest.fixture
def installed(repo, launchd):
    """v0.1.0 installed; v0.2.0 tagged since, two commits later."""
    commit(repo, "First")
    tag(repo, "v0.1.0")
    schedule.install(resolve_paths(), repo)
    commit(repo, "Add /review")
    commit(repo, "Fix Verify")
    tag(repo, "v0.2.0")
    commit(repo, "Work in progress")
    tag(repo, "v0.3.0-rc1")
    launchd.synced.clear()
    return resolve_paths()


def test_release_status_lists_the_commits_of_a_newer_release(repo, installed):
    status = release.release_status(installed, repo)
    assert status == release.ReleaseStatus("v0.1.0", "v0.2.0", ["Fix Verify", "Add /review"])
    assert status.update_available


def test_release_status_without_a_checkout_has_nothing_installed(repo, launchd):
    commit(repo, "First")
    tag(repo, "v0.1.0")
    status = release.release_status(resolve_paths(), repo)
    assert status == release.ReleaseStatus(None, "v0.1.0")
    assert not status.update_available


def test_update_moves_to_the_newest_release_then_does_nothing(repo, installed, launchd):
    assert schedule.update(installed, repo) == schedule.Updated(
        "v0.1.0", "v0.2.0", ["Fix Verify", "Add /review"]
    )
    assert release.installed(installed) == "v0.2.0"
    assert launchd.synced == [installed.app]
    assert not release.release_status(installed, repo).update_available

    assert schedule.update(installed, repo) is None
    assert launchd.synced == [installed.app]


def test_update_refuses_a_downgrade(repo, installed, launchd):
    schedule.update(installed, repo)
    git(repo, "tag", "-d", "v0.2.0")  # the newest Release is v0.1.0 again
    with pytest.raises(release.ReleaseError, match="downgrade"):
        schedule.update(installed, repo)
    assert git(installed.app, "log", "-1", "--format=%s") == "Fix Verify"
    status = release.release_status(installed, repo)
    assert status.newest == "v0.1.0" and not status.update_available


def test_update_needs_an_installed_release(repo, launchd):
    commit(repo, "First")
    tag(repo, "v0.1.0")
    with pytest.raises(release.ReleaseError, match="phy schedule install"):
        schedule.update(resolve_paths(), repo)


def test_status_reports_the_job_the_release_and_the_last_run(repo, installed, launchd):
    assert schedule.status(installed) == schedule.ScheduleStatus(
        loaded=True, installed="v0.1.0", last_run_at=None, last_exit=None
    )
    db.set_state(db.connect(installed.db), "daily.last_run_at", "2026-10-26T06:00:03+00:00")
    launchd.last_exit = "0"
    assert schedule.status(installed) == schedule.ScheduleStatus(
        loaded=True, installed="v0.1.0", last_run_at="2026-10-26T06:00:03+00:00", last_exit="0"
    )


def test_uninstall_unloads_the_job_and_removes_the_plist_and_the_worktree(repo, installed, launchd):
    schedule.uninstall(installed, repo)
    assert not launchd.loaded
    assert not schedule.agent_plist().exists()
    assert not installed.app.exists()
    assert "app" not in git(repo, "worktree", "list")
    assert schedule.status(installed) == schedule.ScheduleStatus(False, None, None, None)
    schedule.uninstall(installed, repo)  # again: nothing left to remove


@pytest.fixture
def cli(repo, monkeypatch):
    monkeypatch.setattr(config, "REPO", repo)
    return lambda *args: CliRunner().invoke(app, ["schedule", *args])


def test_phy_schedule_install_refuses_without_a_release(cli, repo, launchd):
    commit(repo, "First")
    result = cli("install")
    assert result.exit_code == 1
    assert "no Release" in result.output


def test_phy_schedule_install_then_status(cli, repo, launchd):
    commit(repo, "First")
    tag(repo, "v0.1.0")
    result = cli("install")
    assert result.exit_code == 0, result.output
    assert "installed v0.1.0" in result.stdout

    result = cli("status")
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == [
        "job: loaded (phy.daily, 06:00 daily and at login)",
        "release: v0.1.0",
        "last run: never",
    ]


def test_phy_schedule_update_prints_the_commits(cli, installed):
    result = cli("update")
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == [
        "updated v0.1.0 -> v0.2.0 (2 commits):",
        "  Fix Verify",
        "  Add /review",
    ]
    assert cli("update").stdout == "already on the newest Release, v0.2.0\n"


def test_phy_schedule_update_waits_for_no_run(cli, installed):
    with phy_lock(installed):
        result = cli("update")
    assert result.exit_code == 0
    assert release.installed(installed) == "v0.1.0"


def test_phy_schedule_uninstall(cli, installed, launchd):
    result = cli("uninstall")
    assert result.exit_code == 0, result.output
    assert not launchd.loaded and not installed.app.exists()
