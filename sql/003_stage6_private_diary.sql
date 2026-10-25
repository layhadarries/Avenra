BEGIN;
ALTER TABLE avenra.device_enrollments ADD COLUMN IF NOT EXISTS staff_auth_version INTEGER;
ALTER TABLE avenra.device_enrollments ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES avenra.users(id);
CREATE TABLE IF NOT EXISTS avenra.diary_objects (
 object_name TEXT PRIMARY KEY,
 data BYTEA NOT NULL,
 sha256 TEXT NOT NULL,
 byte_count INTEGER NOT NULL CHECK(byte_count>0 AND byte_count<=8388608)
);
ALTER TABLE avenra.diary_objects ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON avenra.diary_objects FROM PUBLIC, anon, authenticated;
INSERT INTO avenra.app_metadata(key,value) VALUES('stage6_private_diary','1') ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value;
CREATE TABLE IF NOT EXISTS avenra.worker_state (
 key TEXT PRIMARY KEY, last_seen_at TEXT NOT NULL, processed INTEGER NOT NULL,
 release TEXT NOT NULL
);
ALTER TABLE avenra.worker_state ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON avenra.worker_state FROM PUBLIC,anon,authenticated;
COMMIT;
