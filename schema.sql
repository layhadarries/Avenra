-- Avenra schema. db.migrate performs additive upgrades for existing databases.
-- Never delete a database to apply an upgrade. Back up before a deployment.

CREATE TABLE IF NOT EXISTS shelters (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL UNIQUE,
    lat             REAL,
    lng             REAL,
    beds_total      INTEGER NOT NULL DEFAULT 0,
    beds_available  INTEGER NOT NULL DEFAULT 0,
    accepting       INTEGER NOT NULL DEFAULT 1,
    languages       TEXT,
    hours           TEXT,
    walk_ins        INTEGER NOT NULL DEFAULT 0,
    verified        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS users (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    role           TEXT NOT NULL CHECK (role IN ('survivor','responder','shelter','admin')),
    email          TEXT NOT NULL UNIQUE,
    password_hash  TEXT,                      -- NULL = cannot sign in (the survivor device user)
    org            TEXT,
    case_code      TEXT UNIQUE,               -- survivors only, e.g. SP-1042
    shelter_id     INTEGER REFERENCES shelters(id), -- shelter staff only
    is_active      INTEGER NOT NULL DEFAULT 0 CHECK(is_active IN (0,1)),
    auth_version   INTEGER NOT NULL DEFAULT 1 CHECK(auth_version>=1)
);

CREATE TABLE IF NOT EXISTS contacts (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id  INTEGER NOT NULL REFERENCES users(id),
    name     TEXT NOT NULL,
    phone    TEXT NOT NULL,
    UNIQUE (user_id, name)
);

CREATE TABLE IF NOT EXISTS alerts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL REFERENCES users(id),
    case_code        TEXT NOT NULL,
    lat              REAL,
    lng              REAL,
    location_accuracy REAL,
    location_recorded_at TEXT,
    status           TEXT NOT NULL DEFAULT 'new'
                     CHECK (status IN ('new','acknowledged','in_progress','resolved')),
    acknowledged_by  TEXT,
    acknowledged_at  TEXT,                    -- UTC, set once by the first responder to acknowledge
    client_id        TEXT UNIQUE,             -- lets offline alerts be replayed without duplicates
    client_ts        TEXT,                    -- when she pressed the button (phone clock, UTC)
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))  -- server clock
);

CREATE TABLE IF NOT EXISTS referrals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id        INTEGER NOT NULL REFERENCES alerts(id),
    shelter_id      INTEGER NOT NULL REFERENCES shelters(id),
    status          TEXT NOT NULL DEFAULT 'sent'
                    CHECK (status IN ('sent','accepted','declined','placed')),
    decline_reason  TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS diary_entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    note        TEXT,
    photo_path  TEXT,
    file_hash   TEXT,
    shared      INTEGER NOT NULL DEFAULT 0,
    client_id   TEXT UNIQUE,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- Unused until Stage 4 (consent records).
CREATE TABLE IF NOT EXISTS consents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    item        TEXT NOT NULL,
    granted_to  TEXT NOT NULL,
    granted_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    revoked_at  TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    actor      TEXT NOT NULL,
    action     TEXT NOT NULL,
    case_code  TEXT,
    detail     TEXT
);

CREATE INDEX IF NOT EXISTS idx_alerts_created ON alerts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_ts       ON audit_log(ts DESC);

-- Additive portal upgrade: existing records are preserved. Grants are explicit,
-- never inferred from free-text organisation names or an administrator role.
CREATE TABLE IF NOT EXISTS case_access (
    staff_id INTEGER NOT NULL REFERENCES users(id),
    survivor_id INTEGER NOT NULL REFERENCES users(id),
    PRIMARY KEY (staff_id, survivor_id)
);
CREATE TABLE IF NOT EXISTS alert_workflow (
    alert_id INTEGER PRIMARY KEY REFERENCES alerts(id),
    assigned_to INTEGER REFERENCES users(id),
    escalated_at TEXT,
    revision INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS alert_history (
    id INTEGER PRIMARY KEY,
    alert_id INTEGER NOT NULL REFERENCES alerts(id),
    actor_id INTEGER REFERENCES users(id),
    action TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_alert_history ON alert_history(alert_id, id);
