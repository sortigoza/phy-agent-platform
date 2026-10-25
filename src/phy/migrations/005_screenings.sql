-- One row per screened Paper version, written by Filter. A pre-filter fail has no scores and
-- points at the Filter run that screened it; a Candidate points at its own Filter call's run.
-- `filter --force` replaces the row in place.

CREATE TABLE screenings (
    arxiv_id       TEXT NOT NULL,
    version        INTEGER NOT NULL,
    prefilter      TEXT NOT NULL CHECK (prefilter IN ('pass', 'fail', 'skipped')),
    scores_json    TEXT,  -- {"Q1": {"reason": ..., "score": ...}, ...}, null for a pre-filter fail
    best_score     REAL,
    screened_in    INTEGER NOT NULL CHECK (screened_in IN (0, 1)),
    model          TEXT,
    prompt_version TEXT,
    run_id         TEXT NOT NULL REFERENCES runs (id),
    created_at     TEXT NOT NULL,
    PRIMARY KEY (arxiv_id, version),
    FOREIGN KEY (arxiv_id, version) REFERENCES paper_versions (arxiv_id, version)
);

CREATE INDEX screenings_run_id ON screenings (run_id);
