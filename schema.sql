CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    bin TEXT NOT NULL UNIQUE
        CHECK (length(bin) = 12 AND bin NOT GLOB '*[^0-9]*'),
    phone TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new'
        CHECK (status IN ('new', 'no_answer', 'refused', 'meeting_set'))
);

CREATE TABLE IF NOT EXISTS managers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meetings (
    id INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    manager_id INTEGER NOT NULL REFERENCES managers(id),
    start_at TEXT NOT NULL,
    original_start_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'scheduled'
        CHECK (status IN ('scheduled', 'cancelled'))
);

CREATE TABLE IF NOT EXISTS calls (
    id INTEGER PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    result TEXT NOT NULL
        CHECK (result IN ('no_answer', 'refused', 'meeting_set')),
    meeting_id INTEGER REFERENCES meetings(id),
    created_at TEXT NOT NULL,
    CHECK (
        (result = 'meeting_set' AND meeting_id IS NOT NULL)
        OR (result IN ('no_answer', 'refused') AND meeting_id IS NULL)
    )
);

INSERT OR IGNORE INTO managers (id, name) VALUES (1, 'Manager 1');
INSERT OR IGNORE INTO managers (id, name) VALUES (2, 'Manager 2');
