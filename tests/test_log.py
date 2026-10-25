import json
import logging
from datetime import date, timedelta

import pytest
import structlog

from phy import log as phy_log
from phy.config import resolve_paths


@pytest.fixture
def paths(phy_home):
    phy_home.mkdir()
    yield resolve_paths()
    structlog.contextvars.clear_contextvars()


def jsonl_events(paths):
    path = paths.log_file(date.today())
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_event_lands_in_both_sinks_with_bound_context(paths, capsys):
    phy_log.configure(paths)
    structlog.contextvars.bind_contextvars(
        run_id="r-1", stage="watch", arxiv_id="1904.12072", version=2
    )
    structlog.get_logger().info("watch.finished", harvested=12, duration_ms=830)

    [event] = [e for e in jsonl_events(paths) if e["event"] == "watch.finished"]
    assert event["run_id"] == "r-1"
    assert event["stage"] == "watch"
    assert event["arxiv_id"] == "1904.12072"
    assert event["version"] == 2
    assert event["harvested"] == 12
    assert event["level"] == "info"
    assert "timestamp" in event
    stderr = capsys.readouterr().err
    assert "watch.finished" in stderr
    assert "harvested=12" in stderr


def test_secret_like_keys_are_not_logged(paths, capsys):
    phy_log.configure(paths)
    structlog.get_logger().info(
        "auth.checked", api_key="sk-ant-secret1", authorization="Bearer secret2", tokens_in=5
    )
    stderr = capsys.readouterr().err
    text = paths.log_file(date.today()).read_text()
    for sink in (text, stderr):
        assert "secret1" not in sink
        assert "secret2" not in sink
    [event] = [e for e in jsonl_events(paths) if e["event"] == "auth.checked"]
    assert event["tokens_in"] == 5


def test_debug_only_with_verbose(paths):
    phy_log.configure(paths)
    structlog.get_logger().debug("arxiv.requested")
    assert not [e for e in jsonl_events(paths) if e["event"] == "arxiv.requested"]

    phy_log.configure(paths, verbose=True)
    structlog.get_logger().debug("arxiv.requested")
    assert [e for e in jsonl_events(paths) if e["event"] == "arxiv.requested"]


def test_stdlib_logs_are_routed_and_noisy_libraries_capped(paths):
    phy_log.configure(paths, verbose=True)
    logging.getLogger("phy.something").warning("stdlib warning")
    logging.getLogger("httpx").info("httpx chatter")
    logging.getLogger("anthropic").debug("sdk chatter")
    events = [e["event"] for e in jsonl_events(paths)]
    assert "stdlib warning" in events
    assert "httpx chatter" not in events
    assert "sdk chatter" not in events


def test_only_the_last_30_days_of_logs_are_kept(paths):
    paths.logs.mkdir()
    today = date.today()
    old = paths.log_file(today - timedelta(days=30))
    kept = paths.log_file(today - timedelta(days=29))
    other = paths.logs / "launchd.err"
    for f in (old, kept, other):
        f.write_text("x\n")
    phy_log.configure(paths)
    assert not old.exists()
    assert kept.exists()
    assert other.exists()
