"""`phy flags`: the Flags of a recent window grouped by field and kind, as input for Meta-work.
A field groups every item of a list, so `key_results[0]` and `key_results[3]` count together.
Never takes `phy.lock`.
"""

import re
import sqlite3
from collections import Counter
from datetime import UTC, datetime, timedelta

from phy import db
from phy.config import Paths, load_config

INDEX = re.compile(r"\[\d+\]")


def since(paths: Paths, window: timedelta, now: datetime | None = None) -> list[sqlite3.Row]:
    """Raises ConfigError for invalid config, as every command does."""
    load_config(paths)
    start = (now or datetime.now(UTC)) - window
    conn = db.connect(paths.db)
    try:
        return db.flags_since(conn, start.isoformat(timespec="seconds"))
    finally:
        conn.close()


def render(flags: list[sqlite3.Row], window: timedelta) -> str:
    lines = [f"last {window.days} days: {len(flags)} Flag{'s' * (len(flags) != 1)}"]
    by_field: dict[str, list[sqlite3.Row]] = {}
    for f in flags:
        by_field.setdefault(INDEX.sub("", f["field_path"]), []).append(f)
    for field, rows in sorted(by_field.items(), key=lambda item: (-len(item[1]), item[0])):
        lines.append(f"{field}: {len(rows)}")
        kinds = Counter(f["kind"] for f in rows)
        for kind, n in sorted(kinds.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"  {kind}: {n}")
            for f in rows:
                if f["kind"] == kind:
                    note = f": {f['note']}" if f["note"] else ""
                    lines.append(f"    {f['arxiv_id']}v{f['version']} {f['field_path']}{note}")
    return "\n".join(lines)
