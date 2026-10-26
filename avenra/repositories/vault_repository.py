"""Survivor evidence credentials and device-bound short-lived read grants."""
from avenra.repositories.base import BaseRepository

SCHEMA = '''
CREATE TABLE IF NOT EXISTS survivor_vaults (
 user_id INTEGER PRIMARY KEY REFERENCES users(id), passphrase_hash TEXT NOT NULL,
 credential_version INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS evidence_unlocks (
 token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
 device_hash TEXT NOT NULL, credential_version INTEGER NOT NULL, expires_at INTEGER NOT NULL
)
'''


class VaultRepository(BaseRepository):
    def credential(self, uid):
        return self.conn.execute('SELECT * FROM survivor_vaults WHERE user_id=?',(uid,)).fetchone()

    def create(self, uid, password_hash):
        self.conn.execute('INSERT INTO survivor_vaults(user_id,passphrase_hash) VALUES(?,?)',(uid,password_hash))

    def grant(self, uid, device_hash, token_hash, version, now):
        self.conn.execute('DELETE FROM evidence_unlocks WHERE expires_at<=?',(now,))
        self.conn.execute('DELETE FROM evidence_unlocks WHERE user_id=? AND device_hash=?',(uid,device_hash))
        self.conn.execute('INSERT INTO evidence_unlocks(token_hash,user_id,device_hash,credential_version,expires_at) VALUES(?,?,?,?,?)',
            (token_hash,uid,device_hash,version,now+900))

    def valid(self, uid, device_hash, token_hash, now):
        return self.conn.execute('''SELECT 1 FROM evidence_unlocks e JOIN survivor_vaults v ON v.user_id=e.user_id
            WHERE e.token_hash=? AND e.user_id=? AND e.device_hash=? AND e.expires_at>?
            AND e.credential_version=v.credential_version''',(token_hash,uid,device_hash,now)).fetchone() is not None

    def revoke(self, uid, device_hash, token_hash):
        self.conn.execute('DELETE FROM evidence_unlocks WHERE user_id=? AND device_hash=? AND token_hash=?',(uid,device_hash,token_hash))
