-- One row per Card, written by Read as a draft and filled in by Verify. Card fields live only in
-- card_json. A Paper version has at most one Card; `read --force` replaces it in place.

CREATE TABLE cards (
    id                    INTEGER PRIMARY KEY,
    arxiv_id              TEXT NOT NULL,
    version               INTEGER NOT NULL,
    card_json             TEXT NOT NULL,
    status                TEXT NOT NULL CHECK (status IN ('draft', 'verified', 'reviewed', 'stale')),
    unsupported_count     INTEGER,
    inferred_count        INTEGER,
    invented_numbers_json TEXT,
    warnings_json         TEXT,
    model                 TEXT NOT NULL,
    prompt_version        TEXT NOT NULL,
    schema_version        TEXT NOT NULL,
    run_id                TEXT NOT NULL REFERENCES runs (id),
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    UNIQUE (arxiv_id, version),
    FOREIGN KEY (arxiv_id, version) REFERENCES paper_versions (arxiv_id, version)
);

CREATE INDEX cards_status ON cards (status);

-- Cache writes cost more than plain input, so the Tracer records them next to cache reads.
-- tokens_in counts uncached input only.
ALTER TABLE runs ADD COLUMN cache_write_tokens INTEGER;
