"""`phy init`: create `$PHY_HOME` and check that the installation can run.

Seeds the instance config from `phy/defaults/` without overwriting anything, runs `git init`
only if `$PHY_HOME` has no repo (phy never commits), creates the database, and makes one cheap
API call to check credentials. Running it again changes nothing.
"""

import subprocess
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

import structlog

from phy import db, llm
from phy.config import Paths, load_config, load_questions

log = structlog.get_logger()

DEFAULTS = files("phy") / "defaults"


@dataclass
class InitReport:
    created: list[str]
    git_initialized: bool
    credential_source: str


def run(paths: Paths) -> InitReport:
    paths.home.mkdir(parents=True, exist_ok=True)
    created = [
        str(target.relative_to(paths.home))
        for default, target in [
            ("config.toml", paths.config_toml),
            ("questions.yaml", paths.questions_yaml),
            ("manifest.yaml", paths.golden_manifest),
            ("CHANGELOG.md", paths.changelog),
            ("gitignore", paths.gitignore),
        ]
        if _seed(DEFAULTS / default, target)
    ]

    config = load_config(paths)
    load_questions(paths)

    git_initialized = not paths.git_dir.exists()
    if git_initialized:
        subprocess.run(["git", "init", "-q", str(paths.home)], check=True)

    if not paths.db.exists():
        created.append(paths.db.name)
    db.connect(paths.db).close()

    source = llm.check_auth(config.filter.model)
    log.info("init.finished", created=len(created), git_initialized=git_initialized)
    return InitReport(created=created, git_initialized=git_initialized, credential_source=source)


def _seed(default, target: Path) -> bool:
    if target.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(default.read_bytes())
    return True
