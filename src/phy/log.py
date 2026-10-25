"""Logging: structlog, with stdlib logging routed through the same processors.

Readable lines go to stderr and the same events as JSON lines to
`$PHY_HOME/logs/phy-YYYY-MM-DD.jsonl`, kept 30 days. Event names are fixed `<area>.<past_tense>`
strings with variables in keys; bind `run_id`, `stage`, `arxiv_id` and `version` with
`structlog.contextvars.bind_contextvars`. Secret-like keys are redacted before any sink.
"""

import logging
import re
import sys
from datetime import date, timedelta

import structlog

from phy.config import Paths

RETENTION_DAYS = 30
NOISY_LIBRARIES = ["httpx", "httpx2", "httpcore", "anthropic", "urllib3"]
SECRET_KEY = re.compile(
    r"(^|_)(key|secret|password|authorization|token|credentials?)$", re.IGNORECASE
)


def _redact_secrets(_logger, _method, event_dict):
    for key in event_dict:
        if SECRET_KEY.search(key):
            event_dict[key] = "[redacted]"
    return event_dict


SHARED_PROCESSORS = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_log_level,
    structlog.processors.TimeStamper(fmt="iso", utc=True),
    _redact_secrets,
]


class DailyFileHandler(logging.Handler):
    """Appends to the file for the current local date, switching files at midnight."""

    def __init__(self, paths: Paths):
        super().__init__()
        self.paths = paths
        self._day: date | None = None
        self._stream = None

    def emit(self, record: logging.LogRecord) -> None:
        try:
            today = date.today()
            if today != self._day:
                self.close_stream()
                self.paths.logs.mkdir(parents=True, exist_ok=True)
                self._stream = open(self.paths.log_file(today), "a")  # noqa: SIM115
                self._day = today
            self._stream.write(self.format(record) + "\n")
            self._stream.flush()
        except Exception:
            self.handleError(record)

    def close_stream(self) -> None:
        if self._stream:
            self._stream.close()
            self._stream = None

    def close(self) -> None:
        self.close_stream()
        super().close()


def log_failure(logger, event: str, error: Exception, expected: tuple, **keys) -> None:
    """Log a handled failure once at ERROR: an `expected` error by its message, anything else
    (a bug) with its traceback."""
    if isinstance(error, expected):
        logger.error(event, error=str(error), **keys)
    else:
        logger.exception(event, error=str(error), **keys)


_installed: list[logging.Handler] = []


def configure(paths: Paths, verbose: bool = False) -> None:
    """Set up both sinks. Safe to call again (tests, `-v` after defaults)."""
    structlog.configure(
        processors=[*SHARED_PROCESSORS, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )

    def formatter(*renderer):
        return structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=SHARED_PROCESSORS,
            processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, *renderer],
        )

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter(structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())))
    jsonl = DailyFileHandler(paths)
    # The console renders tracebacks itself; JSON needs them as a string under `exception`.
    jsonl.setFormatter(
        formatter(structlog.processors.format_exc_info, structlog.processors.JSONRenderer())
    )

    root = logging.getLogger()
    for handler in _installed:
        root.removeHandler(handler)
        handler.close()
    _installed[:] = [console, jsonl]
    for handler in _installed:
        root.addHandler(handler)
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for name in NOISY_LIBRARIES:
        logging.getLogger(name).setLevel(logging.WARNING)

    _remove_old_logs(paths)


def _remove_old_logs(paths: Paths) -> None:
    if not paths.logs.is_dir():
        return
    oldest_kept = date.today() - timedelta(days=RETENTION_DAYS - 1)
    for f in paths.logs.iterdir():
        day = paths.log_file_day(f)
        if day and day < oldest_kept:
            f.unlink()
