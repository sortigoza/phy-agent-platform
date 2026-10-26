"""The `/runs` list and the `/runs/<id>` run viewer (SPEC §9): what each Stage run sent and got
back, read from its `runs` row and the Tracer's JSONL log.
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, get_args
from urllib.parse import urlencode

from phy.config import Paths

Status = Literal["ok", "failed", "skipped", "aborted"]
# Statuses of runs that end before their model call: the viewer shows only their error line.
NO_CALL = ("skipped", "aborted")
# `/runs?since=`: `7d`, `week`, `2026-10-19` or `2026-10-19T06:00:00+00:00`.
SINCE = r"^(\d+d|week|\d{4}-\d{2}-\d{2}(T[\d:.]+(Z|[+-]\d{2}:\d{2})?)?)$"


def arxiv_ids(ids: str | None) -> list[str] | None:
    """`ids=` as a list of arXiv ids; None when it names none."""
    return [i for i in (ids or "").replace(" ", "").split(",") if i] or None


def since_start(since: str, now: datetime) -> str:
    """The start of a `since=` window, as an ISO timestamp comparable with `started_at`: `<n>d`
    is the last n × 24 h, `week` is from Monday 00:00 UTC. Raises ValueError for a bad date."""
    if since == "week":
        monday = now.date() - timedelta(days=now.weekday())
        return datetime(monday.year, monday.month, monday.day, tzinfo=UTC).isoformat()
    if since.endswith("d"):
        return (now - timedelta(days=int(since[:-1]))).isoformat(timespec="seconds")
    start = datetime.fromisoformat(since)
    if len(since) == len("2026-10-19"):
        return since
    return (start if start.tzinfo else start.replace(tzinfo=UTC)).astimezone(UTC).isoformat()


def status_pills(others: dict[str, str], status: str | None) -> list[tuple[str, str, bool]]:
    """The status pills as (label, href, on); each keeps the rest of the filter."""
    return [
        (label, "/runs?" + urlencode(others | ({"status": s} if s else {})), s == status)
        for label, s in [("all", None)] + [(s, s) for s in get_args(Status)]
    ]


@dataclass(frozen=True)
class RunRow:
    """One run as `/runs` lists it, with every value formatted; blank when there is none."""

    id: str
    stage: str
    paper: str
    status: str
    model: str
    prompt: str
    tokens: str
    cost: str
    duration: str
    started: str


def row(run: sqlite3.Row) -> RunRow:
    return RunRow(
        id=run["id"],
        stage=run["stage"],
        paper=run["arxiv_id"] or "",
        status=run["status"],
        model=run["model"] or "",
        prompt=run["prompt_version"] or "",
        tokens=_tokens(run),
        cost="" if run["cost_usd"] is None else f"${run['cost_usd']:.4f}",
        duration=_duration(run["started_at"], run["ended_at"]),
        started=run["started_at"][:16].replace("T", " "),
    )


def _input_tokens(run: sqlite3.Row) -> int:
    """All input tokens: `tokens_in` counts only the uncached ones."""
    return sum(run[k] or 0 for k in ["tokens_in", "cache_read_tokens", "cache_write_tokens"])


def _tokens(run: sqlite3.Row) -> str:
    if run["tokens_out"] is None:
        return ""
    return f"{_input_tokens(run):,} / {run['tokens_out']:,}"


def _duration(started_at: str, ended_at: str | None) -> str:
    """`m:ss`, blank while the run has no end."""
    if ended_at is None:
        return ""
    seconds = round(
        (datetime.fromisoformat(ended_at) - datetime.fromisoformat(started_at)).total_seconds()
    )
    return f"{seconds // 60}:{seconds % 60:02d}"


@dataclass(frozen=True)
class Block:
    """One piece of the prompt: the paper text is folded, the rest shown as is."""

    role: str
    text: str
    paper: bool


@dataclass(frozen=True)
class Call:
    """One model call, as the Tracer wrote it to the run's JSONL log."""

    at: str
    model: str
    settings: str  # max_tokens and effort
    blocks: list[Block]
    schema: str | None
    response: str | None  # the raw response body, pretty-printed
    stop_reason: str | None
    output: str | None  # the parsed output, pretty-printed
    output_error: str | None  # why the output could not be parsed
    error: str | None
    usage: dict[str, int]
    cost_usd: float
    duration_ms: int | None


@dataclass(frozen=True)
class RunView:
    row: RunRow
    error: str | None
    total_cost: str
    log_path: str | None
    calls: list[Call]
    unreadable: int  # log lines that are not JSON, such as one cut off by a crash
    missing_log: bool
    no_call: bool  # the run made no model call, so only its error line is shown


def view(paths: Paths, run: sqlite3.Row) -> RunView:
    no_call = run["status"] in NO_CALL or run["log_path"] is None
    log = paths.home / run["log_path"] if run["log_path"] else None
    missing = not no_call and not log.is_file()
    calls, unreadable = [], 0
    for line in [] if no_call or missing else log.read_text().splitlines():
        if not line.strip():
            continue
        try:
            calls.append(_call(json.loads(line)))
        except json.JSONDecodeError:
            unreadable += 1
    return RunView(
        row=row(run),
        error=run["error"],
        total_cost=f"${run['cost_usd'] or 0:.4f}",
        log_path=run["log_path"],
        calls=calls,
        unreadable=unreadable,
        missing_log=missing,
        no_call=no_call,
    )


def _call(line: dict) -> Call:
    request, response = line["request"], line["response"]
    output_config = request.get("output_config") or {}
    output, output_error = None, None
    if response:
        text = "".join(b["text"] for b in response.get("content", []) if b["type"] == "text")
        try:
            output = _pretty(json.loads(text))
        except json.JSONDecodeError as e:
            output_error = f"not valid JSON ({e.msg} at character {e.pos}): {text}"
    usage = (response or {}).get("usage") or {}
    return Call(
        at=line["at"],
        model=request.get("model", ""),
        settings=f"max_tokens {request.get('max_tokens')}, effort {output_config.get('effort')}",
        blocks=_blocks(request),
        schema=_pretty(output_config["format"]) if "format" in output_config else None,
        response=_pretty(response) if response else None,
        stop_reason=response.get("stop_reason") if response else None,
        output=output,
        output_error=output_error,
        error=line["error"],
        usage={
            "uncached input": usage.get("input_tokens") or 0,
            "output": usage.get("output_tokens") or 0,
            "cache reads": usage.get("cache_read_input_tokens") or 0,
            "cache writes": usage.get("cache_creation_input_tokens") or 0,
        },
        cost_usd=line["cost_usd"],
        duration_ms=line["duration_ms"],
    )


def _blocks(request: dict) -> list[Block]:
    """The system prompt and every message, in order, as text blocks."""
    turns = [("system", request.get("system") or [])] + [
        (m["role"], m["content"]) for m in request.get("messages", [])
    ]
    blocks = []
    for role, content in turns:
        parts = [{"text": content}] if isinstance(content, str) else content
        for part in parts:
            text = part.get("text", "")
            blocks.append(Block(role, text, paper=text.startswith("<paper>")))
    return blocks


def _pretty(value) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False)
