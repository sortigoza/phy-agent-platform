-- One row per Paper and per Paper version, upserted from arXivRaw by Watch (and by Read for a
-- Paper it has not seen). The source columns are filled by Read when it downloads the version.

CREATE TABLE papers (
    arxiv_id         TEXT PRIMARY KEY,
    latest_version   INTEGER NOT NULL,
    title            TEXT NOT NULL,
    authors          TEXT NOT NULL,
    abstract         TEXT NOT NULL,
    categories       TEXT NOT NULL,  -- space-separated, primary first, as arXivRaw gives them
    primary_category TEXT NOT NULL,
    license          TEXT,
    sets             TEXT NOT NULL,  -- space-separated OAI setSpecs, cross-lists included
    first_seen_at    TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE TABLE paper_versions (
    arxiv_id             TEXT NOT NULL REFERENCES papers (arxiv_id),
    version              INTEGER NOT NULL,
    submitted_at         TEXT NOT NULL,
    first_seen_datestamp TEXT NOT NULL,
    source_type          TEXT CHECK (source_type IN ('latex', 'pdf')),
    local_path           TEXT,  -- relative to $PHY_HOME
    sha256               TEXT,
    fetched_at           TEXT,
    PRIMARY KEY (arxiv_id, version)
);
