import json
import subprocess
from pathlib import Path

import httpx
import pytest
import respx
from typer.testing import CliRunner

from phy.cli import app
from phy.config import resolve_paths
from phy.ctx import Ctx
from phy.tracer import LocalTracer

REPO = Path(__file__).parent.parent
MESSAGES_URL = "https://api.anthropic.com/v1/messages"
PONG = {
    "id": "msg_01",
    "type": "message",
    "role": "assistant",
    "model": "claude-haiku-5-5",
    "content": [{"type": "text", "text": "pong"}],
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {"input_tokens": 8, "output_tokens": 2},
}
SEEDED = ["config.toml", "questions.yaml", "golden/manifest.yaml", "CHANGELOG.md", ".gitignore"]


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    with respx.mock(using="httpx2", assert_all_called=False) as router:
        route = router.post(MESSAGES_URL).mock(return_value=httpx.Response(200, json=PONG))
        yield route


def phy(*args):
    return CliRunner().invoke(app, list(args))


def test_init_creates_home_seeds_files_db_and_repo(phy_home, api):
    result = phy("init")

    assert result.exit_code == 0, result.output
    for name in SEEDED:
        assert (phy_home / name).is_file(), name
    assert (phy_home / "phy.db").is_file()
    assert (phy_home / ".git").is_dir()
    assert "ANTHROPIC_API_KEY" in result.output


def test_init_makes_one_cheap_haiku_call(phy_home, api):
    phy("init")

    assert api.call_count == 1
    body = json.loads(api.calls.last.request.content)
    assert body["model"] == "claude-haiku-5-5"
    assert body["max_tokens"] <= 16


def test_second_init_changes_nothing_and_keeps_edits(phy_home, api):
    assert phy("init").exit_code == 0
    config = phy_home / "config.toml"
    config.write_text(config.read_text().replace("daily_quota = 8", "daily_quota = 5"))
    (phy_home / "CHANGELOG.md").write_text("# mine\n")
    before = {name: (phy_home / name).read_bytes() for name in SEEDED}
    git_config = (phy_home / ".git" / "config").read_bytes()

    result = phy("init")

    assert result.exit_code == 0, result.output
    assert {name: (phy_home / name).read_bytes() for name in SEEDED} == before
    assert (phy_home / ".git" / "config").read_bytes() == git_config
    assert "nothing to create" in result.output


def test_init_does_not_reinit_an_existing_repo(phy_home, api):
    phy_home.mkdir()
    subprocess.run(["git", "init", "-q", str(phy_home)], check=True)
    subprocess.run(["git", "-C", str(phy_home), "config", "phy.test", "kept"], check=True)

    result = phy("init")

    assert result.exit_code == 0, result.output
    assert "git init" not in result.output
    out = subprocess.run(
        ["git", "-C", str(phy_home), "config", "phy.test"], capture_output=True, text=True
    )
    assert out.stdout.strip() == "kept"


def test_missing_credentials_point_at_ant_auth_login(phy_home):
    with respx.mock(using="httpx2", assert_all_called=False) as router:
        route = router.post(MESSAGES_URL)
        result = phy("init")

    assert result.exit_code == 1
    assert "ant auth login" in result.output
    assert not route.called
    assert (phy_home / "config.toml").is_file()


def test_rejected_credentials_are_a_clear_error(phy_home, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-revoked")
    error = {
        "type": "error",
        "error": {"type": "authentication_error", "message": "invalid x-api-key"},
    }
    with respx.mock(using="httpx2") as router:
        router.post(MESSAGES_URL).mock(return_value=httpx.Response(401, json=error))
        result = phy("init")

    assert result.exit_code == 1
    assert "ANTHROPIC_API_KEY" in result.output
    assert "ant auth login" in result.output


def test_invalid_existing_config_fails_init_before_git_db_or_auth(phy_home, api):
    phy_home.mkdir()
    (phy_home / "config.toml").write_text("[watch]\nbackfil_days = 3\n")

    result = phy("init")

    assert result.exit_code == 1
    assert "watch.backfil_days" in result.output
    assert not api.called
    assert not (phy_home / ".git").exists()
    assert not (phy_home / "phy.db").exists()


def test_failed_auth_call_is_a_clear_error_not_a_traceback(phy_home, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    error = {"type": "error", "error": {"type": "not_found_error", "message": "model: nope"}}
    with respx.mock(using="httpx2") as router:
        router.post(MESSAGES_URL).mock(return_value=httpx.Response(404, json=error))
        result = phy("init")

    assert result.exit_code == 1
    assert "auth check call to claude-haiku-5-5 failed (HTTP 404" in result.output


def test_ctx_carries_config_questions_db_and_a_run_id(phy_home, api):
    phy("init")
    ctx = Ctx.load(resolve_paths())
    assert ctx.config.read.daily_quota == 8
    assert ctx.questions.questions[0].id == "Q1"
    assert ctx.db.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
    assert ctx.run_id
    assert isinstance(ctx.tracer, LocalTracer)
    assert Ctx.load(resolve_paths()).run_id != ctx.run_id


def test_version_is_git_describe_of_the_checkout():
    expected = subprocess.run(
        ["git", "describe", "--tags", "--always"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    result = phy("--version")
    assert result.exit_code == 0
    assert result.output.strip() == expected


def test_help_lists_init():
    result = phy("--help")
    assert result.exit_code == 0
    assert "init" in result.output
