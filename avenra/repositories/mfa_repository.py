"""MFA persistence; caller owns transactions and audited credential changes."""
from avenra.repositories.base import BaseRepository

SCHEMA = '''
CREATE TABLE IF NOT EXISTS staff_mfa (
 user_id INTEGER PRIMARY KEY REFERENCES users(id), encrypted_secret TEXT NOT NULL,
 confirmed_at INTEGER, enrollment_expires_at INTEGER NOT NULL, last_counter INTEGER NOT NULL DEFAULT -1
);
CREATE TABLE IF NOT EXISTS staff_mfa_challenges (
 nonce_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
 auth_version INTEGER NOT NULL, expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS staff_mfa_challenge_user ON staff_mfa_challenges(user_id);
CREATE TABLE IF NOT EXISTS staff_recovery_codes (
 user_id INTEGER NOT NULL REFERENCES users(id), digest TEXT NOT NULL, used_at INTEGER,
 PRIMARY KEY(user_id,digest)
)
'''


class MFARepository(BaseRepository):
    def credential(self, uid):
        return self.conn.execute('SELECT * FROM staff_mfa WHERE user_id=?', (uid,)).fetchone()

    def challenge(self, digest, now):
        return self.conn.execute('''SELECT u.* FROM staff_mfa_challenges c JOIN users u ON u.id=c.user_id
            WHERE c.nonce_hash=? AND c.expires_at>? AND u.auth_version=c.auth_version
            AND u.is_active=1 AND u.password_hash IS NOT NULL AND u.role IN ('admin','responder','shelter')''',
            (digest, now)).fetchone()

    def begin(self, uid, version, digest, now):
        self.conn.execute('DELETE FROM staff_mfa_challenges WHERE expires_at<=?', (now,))
        # Bound pending credentials per account without invalidating a confirmed MFA secret.
        self.conn.execute('DELETE FROM staff_mfa_challenges WHERE user_id=? AND nonce_hash NOT IN (SELECT nonce_hash FROM staff_mfa_challenges WHERE user_id=? ORDER BY expires_at DESC LIMIT 4)', (uid, uid))
        self.conn.execute('INSERT INTO staff_mfa_challenges(nonce_hash,user_id,auth_version,expires_at) VALUES(?,?,?,?)',
                          (digest, uid, version, now+300))

    def prepare(self, uid, encrypted_secret, now):
        self.conn.execute('''INSERT INTO staff_mfa(user_id,encrypted_secret,enrollment_expires_at) VALUES(?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET encrypted_secret=excluded.encrypted_secret,
            enrollment_expires_at=excluded.enrollment_expires_at,last_counter=-1
            WHERE staff_mfa.confirmed_at IS NULL AND staff_mfa.enrollment_expires_at<=?''',
            (uid, encrypted_secret, now+300, now))

    def consume_challenge(self, digest):
        return self.conn.execute('DELETE FROM staff_mfa_challenges WHERE nonce_hash=?', (digest,)).rowcount == 1

    def advance_counter(self, uid, counter, now):
        return self.conn.execute('''UPDATE staff_mfa SET last_counter=?,confirmed_at=COALESCE(confirmed_at,?)
            WHERE user_id=? AND last_counter<?''', (counter, now, uid, counter)).rowcount == 1

    def replace_recovery(self, uid, digests):
        self.conn.execute('DELETE FROM staff_recovery_codes WHERE user_id=?', (uid,))
        for digest in digests:
            self.conn.execute('INSERT INTO staff_recovery_codes(user_id,digest) VALUES(?,?)', (uid, digest))

    def consume_recovery(self, uid, digest, now):
        return self.conn.execute('UPDATE staff_recovery_codes SET used_at=? WHERE user_id=? AND digest=? AND used_at IS NULL',
                                 (now, uid, digest)).rowcount == 1

    def reset(self, uid):
        self.conn.execute('DELETE FROM staff_mfa WHERE user_id=?', (uid,))
        self.conn.execute('DELETE FROM staff_recovery_codes WHERE user_id=?', (uid,))
        self.conn.execute('DELETE FROM staff_mfa_challenges WHERE user_id=?', (uid,))
