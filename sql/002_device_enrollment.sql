BEGIN;
CREATE TABLE IF NOT EXISTS avenra.device_enrollments (
 token_hash TEXT PRIMARY KEY, staff_id INTEGER NOT NULL REFERENCES avenra.users(id),
 expires_at INTEGER NOT NULL, consumed_at INTEGER
);
CREATE TABLE IF NOT EXISTS avenra.survivor_devices (
 token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES avenra.users(id),
 expires_at INTEGER NOT NULL, revoked_at INTEGER
);
ALTER TABLE avenra.device_enrollments ENABLE ROW LEVEL SECURITY;
ALTER TABLE avenra.survivor_devices ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON avenra.device_enrollments, avenra.survivor_devices FROM PUBLIC, anon, authenticated;
CREATE TABLE IF NOT EXISTS avenra.device_pairing_attempts (
 bucket TEXT PRIMARY KEY, window_start INTEGER NOT NULL, attempts INTEGER NOT NULL
);
ALTER TABLE avenra.device_pairing_attempts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON avenra.device_pairing_attempts FROM PUBLIC, anon, authenticated;
COMMIT;
