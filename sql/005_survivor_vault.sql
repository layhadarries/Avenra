-- Explicit additive migration only; never automatically applied to hosted storage.
BEGIN;
CREATE TABLE IF NOT EXISTS avenra.survivor_vaults (
 user_id BIGINT PRIMARY KEY REFERENCES avenra.users(id), passphrase_hash TEXT NOT NULL,
 credential_version INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS avenra.evidence_unlocks (
 token_hash TEXT PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES avenra.users(id),
 device_hash TEXT NOT NULL, credential_version INTEGER NOT NULL, expires_at BIGINT NOT NULL
);
ALTER TABLE avenra.survivor_vaults ENABLE ROW LEVEL SECURITY;
ALTER TABLE avenra.evidence_unlocks ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON avenra.survivor_vaults,avenra.evidence_unlocks FROM PUBLIC,anon,authenticated;
INSERT INTO avenra.schema_migrations(version) VALUES(8) ON CONFLICT DO NOTHING;
COMMIT;
