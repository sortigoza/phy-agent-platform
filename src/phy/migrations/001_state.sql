-- Key-value pipeline state (watch.hwm, watch.last_success_at) and one row per Stage execution.

CREATE TABLE state (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE runs (
    id                TEXT PRIMARY KEY,
    stage             TEXT NOT NULL,
    arxiv_id          TEXT,
    status            TEXT NOT NULL,
    error             TEXT,
    model             TEXT,
    prompt_version    TEXT,
    tokens_in         INTEGER,
    tokens_out        INTEGER,
    cache_read_tokens INTEGER,
    cost_usd          REAL,
    started_at        TEXT NOT NULL,
    ended_at          TEXT,
    log_path          TEXT
);

CREATE INDEX runs_started_at ON runs (started_at);
CREATE INDEX runs_stage_started_at ON runs (stage, started_at);
