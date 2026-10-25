-- Additive only; requires explicit operator application, never automatic live DDL.
BEGIN;
CREATE TABLE IF NOT EXISTS avenra.staff_mfa (
 user_id BIGINT PRIMARY KEY REFERENCES avenra.users(id), encrypted_secret TEXT NOT NULL,
 confirmed_at BIGINT, enrollment_expires_at BIGINT NOT NULL, last_counter BIGINT NOT NULL DEFAULT -1
);
CREATE TABLE IF NOT EXISTS avenra.staff_mfa_challenges (
 nonce_hash TEXT PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES avenra.users(id),
 auth_version INTEGER NOT NULL, expires_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS staff_mfa_challenge_user ON avenra.staff_mfa_challenges(user_id);
CREATE TABLE IF NOT EXISTS avenra.staff_recovery_codes (
 user_id BIGINT NOT NULL REFERENCES avenra.users(id), digest TEXT NOT NULL, used_at BIGINT,
 PRIMARY KEY(user_id,digest)
);
CREATE TABLE IF NOT EXISTS avenra.auth_attempts (
 bucket TEXT PRIMARY KEY, window_start BIGINT NOT NULL, attempts INTEGER NOT NULL
);
ALTER TABLE avenra.staff_mfa ENABLE ROW LEVEL SECURITY;
ALTER TABLE avenra.staff_mfa_challenges ENABLE ROW LEVEL SECURITY;
ALTER TABLE avenra.staff_recovery_codes ENABLE ROW LEVEL SECURITY;
ALTER TABLE avenra.auth_attempts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON avenra.staff_mfa,avenra.staff_mfa_challenges,avenra.staff_recovery_codes,avenra.auth_attempts FROM PUBLIC,anon,authenticated;
INSERT INTO avenra.schema_migrations(version) VALUES(7) ON CONFLICT DO NOTHING;
COMMIT;
