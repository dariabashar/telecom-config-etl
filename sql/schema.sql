-- Schema for the telecom configuration warehouse.
-- Every business table is a Type 2 slowly changing dimension: a change never
-- overwrites a row, it closes the old version (valid_to) and opens a new one.

CREATE TABLE IF NOT EXISTS sources (
    id          SERIAL PRIMARY KEY,
    path        TEXT        NOT NULL,          -- logical name of the file, e.g. devices.csv
    format      TEXT        NOT NULL CHECK (format IN ('csv', 'excel', 'json', 'xml')),
    sha256      TEXT        NOT NULL,          -- content hash: same bytes = same source version
    size_bytes  BIGINT      NOT NULL,
    first_seen  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (path, sha256)
);

CREATE TABLE IF NOT EXISTS load_runs (
    id             SERIAL PRIMARY KEY,
    source_id      INTEGER     NOT NULL REFERENCES sources (id),
    started_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at    TIMESTAMPTZ,
    status         TEXT        NOT NULL DEFAULT 'running'
                   CHECK (status IN ('running', 'success', 'success_with_issues', 'failed')),
    rows_read      INTEGER NOT NULL DEFAULT 0,
    rows_valid     INTEGER NOT NULL DEFAULT 0,
    rows_rejected  INTEGER NOT NULL DEFAULT 0,
    rows_inserted  INTEGER NOT NULL DEFAULT 0,   -- brand new keys
    rows_changed   INTEGER NOT NULL DEFAULT 0,   -- new version of an existing key
    rows_unchanged INTEGER NOT NULL DEFAULT 0,
    rows_closed    INTEGER NOT NULL DEFAULT 0,   -- keys that disappeared from the source
    error          TEXT
);
CREATE INDEX IF NOT EXISTS load_runs_source_idx ON load_runs (source_id, id DESC);

CREATE TABLE IF NOT EXISTS validation_issues (
    id         BIGSERIAL PRIMARY KEY,
    run_id     INTEGER NOT NULL REFERENCES load_runs (id) ON DELETE CASCADE,
    row_number INTEGER,                  -- 1-based row in the source (NULL for file-level issues)
    entity     TEXT NOT NULL,
    key        TEXT,
    field      TEXT,
    rule       TEXT NOT NULL,            -- required | format | duplicate_key | unknown_device | ...
    message    TEXT NOT NULL,
    raw        JSONB
);
CREATE INDEX IF NOT EXISTS validation_issues_run_idx ON validation_issues (run_id);

CREATE TABLE IF NOT EXISTS device_versions (
    id          BIGSERIAL PRIMARY KEY,
    hostname    TEXT        NOT NULL,
    vendor      TEXT        NOT NULL,
    model       TEXT,
    site        TEXT        NOT NULL,
    mgmt_ip     INET        NOT NULL,
    role        TEXT        NOT NULL CHECK (role IN ('core', 'aggregation', 'access', 'edge', 'firewall')),
    os_version  TEXT,
    attrs_hash  TEXT        NOT NULL,
    valid_from  TIMESTAMPTZ NOT NULL,
    valid_to    TIMESTAMPTZ,
    is_current  BOOLEAN     NOT NULL DEFAULT TRUE,
    source_id   INTEGER     NOT NULL REFERENCES sources (id),
    run_id      INTEGER     NOT NULL REFERENCES load_runs (id),
    CHECK ((is_current AND valid_to IS NULL) OR (NOT is_current AND valid_to IS NOT NULL))
);
-- at most one open version per device
CREATE UNIQUE INDEX IF NOT EXISTS device_current_uq ON device_versions (hostname) WHERE is_current;
CREATE INDEX IF NOT EXISTS device_history_idx ON device_versions (hostname, valid_from);

CREATE TABLE IF NOT EXISTS interface_versions (
    id           BIGSERIAL PRIMARY KEY,
    hostname     TEXT        NOT NULL,
    name         TEXT        NOT NULL,
    ip_address   INET,
    status       TEXT        NOT NULL CHECK (status IN ('up', 'down', 'admin-down')),
    speed_mbps   INTEGER CHECK (speed_mbps >= 0),
    description  TEXT,
    attrs_hash   TEXT        NOT NULL,
    valid_from   TIMESTAMPTZ NOT NULL,
    valid_to     TIMESTAMPTZ,
    is_current   BOOLEAN     NOT NULL DEFAULT TRUE,
    source_id    INTEGER     NOT NULL REFERENCES sources (id),
    run_id       INTEGER     NOT NULL REFERENCES load_runs (id),
    CHECK ((is_current AND valid_to IS NULL) OR (NOT is_current AND valid_to IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS interface_current_uq ON interface_versions (hostname, name) WHERE is_current;
CREATE INDEX IF NOT EXISTS interface_history_idx ON interface_versions (hostname, name, valid_from);
