-- One row per `phy eval`: the Scores of one run over one split of the Golden set. Eval Cards
-- live whole in per_paper_json and never in `cards`. The baseline and diff columns stay null
-- until the run-to-run diff and `phy eval accept` fill them.

CREATE TABLE eval_runs (
    id                   TEXT PRIMARY KEY REFERENCES runs (id),
    golden_version       INTEGER NOT NULL,
    split                TEXT NOT NULL CHECK (split IN ('dev', 'held_out')),
    prompt_versions_json TEXT NOT NULL,  -- {"read": "v2", "filter": "v1"}
    model                TEXT NOT NULL,  -- the Read model, which writes the eval Cards
    metrics_json         TEXT NOT NULL,
    per_paper_json       TEXT NOT NULL,
    baseline_id          TEXT REFERENCES eval_runs (id),
    diff_json            TEXT,
    material_changes     INTEGER,
    accepted_at          TEXT,
    created_at           TEXT NOT NULL
);

CREATE INDEX eval_runs_created_at ON eval_runs (created_at);
