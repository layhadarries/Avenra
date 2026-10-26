-- Explicit additive migration; logical deletion never claims forensic erasure.
BEGIN;
CREATE TABLE IF NOT EXISTS avenra.retention_holds (
 user_id BIGINT PRIMARY KEY REFERENCES avenra.users(id), reference TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS avenra.deletion_tombstones (
 user_id BIGINT NOT NULL REFERENCES avenra.users(id), kind TEXT NOT NULL, client_id TEXT NOT NULL,
 deleted_at TEXT NOT NULL DEFAULT (to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS"Z"')),
 PRIMARY KEY(user_id,kind,client_id)
);
CREATE TABLE IF NOT EXISTS avenra.retention_runs (
 plan_hash TEXT PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES avenra.users(id), kind TEXT NOT NULL,
 removed INTEGER NOT NULL, reference TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT (to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS"Z"'))
);
CREATE TABLE IF NOT EXISTS avenra.retention_media_jobs (
 user_id BIGINT NOT NULL REFERENCES avenra.users(id), object_name TEXT NOT NULL, expected_sha256 TEXT,
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','failed','blocked','deleted')),
 reason_code TEXT, reference TEXT NOT NULL,
 created_at TEXT NOT NULL DEFAULT (to_char(CURRENT_TIMESTAMP AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS"Z"')),
 PRIMARY KEY(user_id,object_name)
);
ALTER TABLE avenra.retention_holds ENABLE ROW LEVEL SECURITY;
ALTER TABLE avenra.deletion_tombstones ENABLE ROW LEVEL SECURITY;
ALTER TABLE avenra.retention_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE avenra.retention_media_jobs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON avenra.retention_holds,avenra.deletion_tombstones,avenra.retention_runs,avenra.retention_media_jobs FROM PUBLIC,anon,authenticated;
INSERT INTO avenra.schema_migrations(version) VALUES(9) ON CONFLICT DO NOTHING;
COMMIT;
