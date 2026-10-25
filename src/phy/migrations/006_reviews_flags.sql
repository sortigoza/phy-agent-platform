-- One row per Review and per Flag, written by the UI. Added before the UI writes them because
-- Read's selection re-cards a Stale Card only when its latest Review rated it yes or partly.

CREATE TABLE reviews (
    id            INTEGER PRIMARY KEY,
    card_id       INTEGER NOT NULL REFERENCES cards (id),
    relevance     TEXT NOT NULL CHECK (relevance IN ('yes', 'partly', 'no')),
    deep_read     INTEGER NOT NULL DEFAULT 0 CHECK (deep_read IN (0, 1)),
    seconds_spent INTEGER,
    note          TEXT,
    created_at    TEXT NOT NULL
);

CREATE INDEX reviews_card_id ON reviews (card_id);
CREATE INDEX reviews_created_at ON reviews (created_at);

CREATE TABLE flags (
    id         INTEGER PRIMARY KEY,
    card_id    INTEGER NOT NULL REFERENCES cards (id),
    field_path TEXT NOT NULL,
    kind       TEXT NOT NULL
               CHECK (kind IN ('wrong_value', 'quote_doesnt_support', 'missing', 'should_be_opinion')),
    note       TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX flags_card_id ON flags (card_id);
